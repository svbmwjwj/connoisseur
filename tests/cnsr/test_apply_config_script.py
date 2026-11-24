"""apply-config.sh, run by systemd on the node so that it outlives the SSH connection Xray may carry."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="bash is not available on Windows")

SCRIPT = Path(__file__).resolve().parents[2] / "src" / "cnsr" / "assets" / "node" / "apply-config.sh"
BASH = "/bin/bash" if os.path.exists("/bin/bash") else "bash"
PATH_LINE = 'PATH="$PATH:/usr/local/sbin:/usr/sbin:/sbin"\n'

# Each restart records the config Xray comes up with; docker.rc lists the status of each one in turn,
# up.rc that of each `compose up`.
DOCKER = r"""#!/bin/bash
echo "docker $*" >> "$FAKE_DIR/calls"
case "$*" in
    *" up -d") [ ! -f "$FAKE_DIR/up.rc" ] || exit "$(cat "$FAKE_DIR/up.rc")"; exit 0 ;;
esac
cat "$CNSR_ROOT/xray/conf/config.json" >> "$FAKE_DIR/restarts"
if [ -s "$FAKE_DIR/docker.rc" ]; then
    rc=$(head -n 1 "$FAKE_DIR/docker.rc"); tail -n +2 "$FAKE_DIR/docker.rc" > "$FAKE_DIR/rc.tmp"
    cat "$FAKE_DIR/rc.tmp" > "$FAKE_DIR/docker.rc"; exit "$rc"
fi
"""
SYSTEMCTL = '#!/bin/bash\necho "systemctl $*" >> "$FAKE_DIR/calls"\n'
VERIFY = r"""#!/bin/bash
echo "verify $(cat "$1")" >> "$FAKE_DIR/calls"
rm -f "$1"
[ ! -f "$FAKE_DIR/verify.rc" ] || exit "$(cat "$FAKE_DIR/verify.rc")"
"""


class Node:
    def __init__(self, base: Path) -> None:
        self.base, self.root, self.bin = base, base / "cnsr", base / "bin"
        self.conf = self.root / "xray" / "conf"
        for directory in (self.conf, self.root / "bin", self.bin):
            directory.mkdir(parents=True)
        for tool in ("bash", "cat", "cp", "mv", "rm", "touch", "head", "tail"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        self.tool(self.bin / "docker", DOCKER)
        self.tool(self.bin / "systemctl", SYSTEMCTL)
        self.tool(self.root / "bin" / "verify-reality.sh", VERIFY)
        self.unit = base / "cnsr-rotate.service"
        self.unit.write_text("[Service]\n")
        (self.conf / "config.json").write_text("old\n")
        (self.conf / "config.new.json").write_text("new\n")
        (self.root / "verify.env").write_text("UUID=u\n")

    @staticmethod
    def tool(path: Path, text: str) -> None:
        path.write_text(text)
        path.chmod(0o755)

    def run(self, *args: str) -> int:
        text = SCRIPT.read_text()
        assert text.count(PATH_LINE) == 1
        script = self.base / "apply-config.sh"
        script.write_text(text.replace(PATH_LINE, ""))
        env = {"PATH": str(self.bin), "FAKE_DIR": str(self.base), "CNSR_ROOT": str(self.root), "CNSR_ROTATE_UNIT": str(self.unit)}
        return subprocess.run([BASH, str(script), "id1", *args], env=env, timeout=30, stdin=subprocess.DEVNULL).returncode

    def calls(self) -> list[str]:
        path = self.base / "calls"
        return path.read_text().splitlines() if path.exists() else []

    def restarted_with(self) -> list[str]:
        path = self.base / "restarts"
        return path.read_text().splitlines() if path.exists() else []

    def config(self) -> str:
        return (self.conf / "config.json").read_text()

    def result(self) -> str:
        return (self.root / "apply-result").read_text()

    def leftovers(self) -> list[str]:
        names = ["xray/.restart-pending", "verify.env", "apply-result.tmp"]
        return [n for n in names if (self.root / n).exists()] + [p.name for p in self.conf.iterdir() if p.name != "config.json"]


@pytest.fixture
def node(tmp_path) -> Node:
    return Node(tmp_path)


def test_a_config_that_works_stays(node):
    assert node.run() == 0
    assert node.config() == "new\n" and node.restarted_with() == ["new"] and node.result() == "id1 ok\n"
    assert node.leftovers() == []


def test_rotation_is_back_before_the_result_says_so(node):
    node.run()
    assert node.calls()[-1] == "systemctl start cnsr-rotate.service"


def test_a_failed_handshake_puts_the_old_config_back(node):
    (node.base / "verify.rc").write_text("1")
    node.run()
    assert node.config() == "old\n" and node.restarted_with() == ["new", "old"]
    assert node.result() == "id1 rolled-back handshake\n" and node.leftovers() == []
    assert node.calls()[-1] == "systemctl start cnsr-rotate.service"


def test_a_failed_restart_puts_the_old_config_back(node):
    (node.base / "docker.rc").write_text("1\n0\n")
    node.run()
    assert node.config() == "old\n" and node.result() == "id1 rolled-back restart\n"
    assert not any(call.startswith("verify") for call in node.calls()) and node.leftovers() == []


def test_a_rollback_that_cannot_restart_keeps_the_marker_and_says_failed(node):
    (node.base / "docker.rc").write_text("1\n1\n")
    node.run()
    assert node.config() == "old\n" and node.result() == "id1 failed\n"
    assert (node.root / "xray" / ".restart-pending").exists()
    assert node.calls()[-1] == "systemctl start cnsr-rotate.service"


def test_without_a_staged_config_nothing_is_touched(node):
    (node.conf / "config.new.json").unlink()
    node.run()
    assert node.config() == "old\n" and node.restarted_with() == [] and node.result() == "id1 rolled-back staged\n"
    assert node.calls()[-1] == "systemctl start cnsr-rotate.service"


def test_a_node_without_the_rotation_service_starts_none(node):
    node.unit.unlink()
    node.run()
    assert node.result() == "id1 ok\n" and not any(call.startswith("systemctl") for call in node.calls())


def test_the_container_is_brought_up_before_it_is_restarted(node):
    node.run()
    calls = [call for call in node.calls() if call.startswith("docker")]
    assert [call.rsplit(" ", 2)[-1] for call in calls] == ["-d", "restart"]


def test_a_container_that_does_not_come_up_is_a_failed_restart(node):
    (node.base / "up.rc").write_text("1")
    node.run()
    assert node.config() == "old\n" and node.result() == "id1 failed\n"


def test_a_deployment_keeps_the_rotation_service_stopped(node):
    """Its step 9 settles an unfinished switch first; starting earlier would undo the config."""
    node.run("keep-stopped")
    assert node.result() == "id1 ok\n" and not any(call.startswith("systemctl") for call in node.calls())
    (node.conf / "config.new.json").write_text("newer\n")
    (node.root / "verify.env").write_text("UUID=u\n")
    (node.base / "verify.rc").write_text("1")
    node.run("keep-stopped")
    assert "rolled-back" in node.result() and not any(call.startswith("systemctl") for call in node.calls())
