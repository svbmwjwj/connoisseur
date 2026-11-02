# cnsr 部署路径实施计划（计划一：add 与 rm）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `cnsr add` 和 `cnsr rm`：一条命令在 AWS Lightsail 或已有服务器上部署 Xray REALITY 节点，并通过 Cloudflare 控制端向圈X 提供远程资源。

**Architecture:** 本机是 Python 包 `cnsr`（src 布局，uv 管理），用 boto3 操作 Lightsail，用 httpx 调 Cloudflare API，用系统 OpenSSH 子进程操作服务器。服务器端只运行随包分发的短 bash 脚本，经 SSH 标准输入以 `bash -s` 下发。控制端是一个 Cloudflare Worker（两个 ES module 文件）加一个 KV，同时是节点清单的唯一存放处。

**Tech Stack:** Python 3.12、uv、httpx、boto3、cryptography、pytest、botocore Stubber；Cloudflare Workers（JavaScript，用 `node --test` 测试，Node 由开发依赖 `nodejs-wheel-binaries` 在项目环境内提供）；服务器端 bash、curl、ufw、fail2ban、Docker。

**Spec:** `.notes/cnsr-redesign-spec_zh-cn.md`（2026-10-17 定稿）。本计划只覆盖部署路径；自动换 SNI（节点端服务、控制端的 task/report/status/event 接口、圈X 脚本）放在计划二。

## Global Constraints

- Python `>=3.12`，依赖只用 `boto3`、`httpx`、`cryptography`；开发依赖 `pytest`、`nodejs-wheel-binaries`。不做全局安装，一律 `uv add`、`uv run`。
- CLI 输出只用简体中文；源码标识符、注释、commit 信息用英文。
- 本机代码不调用 bash、sed、awk；`ssh`、`ssh-add`、`ssh-keygen`、`icacls` 一律用参数列表调用。路径用 `pathlib`，读文件容忍 CRLF 和 BOM，写文件统一 LF。
- SSH 不使用 ControlMaster，每次调用都带 `-o ControlMaster=no`。
- 区域对照固定为 `jp` → `ap-northeast-1`、`sg` → `ap-southeast-1`、`us` → `us-west-2`；规格 `nano_3_0`；系统优先 `debian_13`，没有时用 `debian_12`。
- Xray 只监听 443；服务器不是全新系统就停下，不改端口、不碰已有服务。
- 节点域名为灰云，TTL 60 秒；有可用的 IPv6 才建 AAAA。
- 新代码将来会发布到新建的公开仓库：代码和测试里不得出现真实 IP、域名、别名或 token。测试数据只用 `192.0.2.0/24`、`198.51.100.0/24`、`203.0.113.0/24`、`2001:db8::/32` 和 `example.com`。
- 单个文件不超过约 400 行；Python 模块用 snake_case，其余文件用 kebab-case。
- 不修改、不移动旧实现的文件（`cnsr.sh`、`cnsr.cmd`、`cnsr.ps1`、`core/`、`lib/`、`providers/`、`gateway/`、`templates/`、`tools/`、旧的 `tests/*.py` 和 `.github/workflows/scan.yml`）。新代码与旧代码在本地并存，新建公开仓库时只带新代码。只有 `pyproject.toml` 和 `uv.lock` 按 Task 1 修改。现有的 GitHub 仓库已决定删除，CI 要等新仓库建好后才会运行，在那之前以本地 `uv run pytest` 为准。工作区里 `templates/compose.yml.template` 的未提交改动保持原样，任何 commit 都不要带上它。
- 只提交本任务的文件（`git add <具体路径>`），不推送。
- 单元测试不连接任何真实服务器或真实 API。真机验证只用东京的 `cnsr-test-` 开头的临时实例，绑定已有的 `jp-key` key pair，测完删除。永远不碰新加坡的生产实例 `prod-sg` 和 `prod-us` 上已有的 `xray` 容器、443 端口与 SSH 配置。

## Review Focus

1. 重装过系统的小厂商服务器 — 主机指纹不符时，应提示你确认，确认后删除旧指纹并重试，而不是直接失败。由 Task 15 的 `test_hostkey_mismatch_prompts_then_forgets` 覆盖。
2. 加固关闭 22 后、验证成功前 SSH 断线 — 服务器必须在 3 分钟内自动恢复到“新旧端口都开”的状态。由 Task 11 的 `test_cut_arms_revert_timer_before_touching_ports` 覆盖。
3. 电脑上开着圈X（TUN 或系统代理）时运行 `add` — 必须在扫描前停下，绝不能从代理节点发出扫描。由 Task 15 的 `test_scan_stops_when_egress_not_direct` 覆盖。
4. 中途失败或按 Ctrl-C 后重跑 — 不重复开实例、不重复建解析、不重置 UUID 和密钥。由 Task 10 的 `test_ensure_instance_reuses_tagged`、Task 12 的 `test_rerun_keeps_domain`、Task 15 的 `test_rerun_preserves_identity` 覆盖。
5. 对一台跑着其他服务的机器执行 `add`（例如别名撞上已有的生产机） — 体检发现异常就停下，不建解析、不加固、不装任何东西；`~/.ssh/config` 里其他条目保持原样。由 Task 7 的 `test_write_block_preserves_other_blocks`、Task 15 的 `test_preflight_findings_stop_before_any_change` 覆盖。

## 文件结构

| 路径 | 职责 |
| :--- | :--- |
| `pyproject.toml` | 改为可安装的包，入口 `cnsr = "cnsr.cli:main"` |
| `.github/workflows/ci.yml` | 三平台跑 pytest，Linux 额外跑 Worker 测试 |
| `src/cnsr/cli.py` | 参数解析、帮助菜单、分发 |
| `src/cnsr/errors.py`、`ui.py` | 面向用户的错误类型；交互与输出 |
| `src/cnsr/paths.py`、`localconf.py` | 各平台路径；本机 `secrets.env` 读写与权限 |
| `src/cnsr/naming.py` | 别名校验、随机前缀 |
| `src/cnsr/state.py` | 节点清单数据模型与 KV 读写 |
| `src/cnsr/qx.py` | 圈X 节点行与客户端配置 |
| `src/cnsr/cloudflare/api.py`、`kv.py`、`dns.py`、`control.py` | Cloudflare 客户端、KV、DNS、控制端部署与外部探测 |
| `src/cnsr/ssh/agent.py`、`config.py`、`remote.py` | agent 与钥匙；`~/.ssh/config` 编辑；远程执行与错误分类 |
| `src/cnsr/aws/fingerprint.py`、`lightsail.py` | Lightsail 指纹；实例、静态 IP、钥匙、防火墙 |
| `src/cnsr/server/preflight.py`、`harden.py`、`baseline.py`、`xray.py` | 体检、加固、AWS 基线、Xray 配置 |
| `src/cnsr/scan/ranges.py`、`egress.py`、`probe.py`、`filters.py`、`select.py` | 扫描范围、直连检查、TLS 探测、过滤、节点验证结果排序 |
| `src/cnsr/deploy/context.py`、`dns_records.py`、`steps.py` | 部署上下文与依赖注入；解析与别名切换；流水线各步 |
| `src/cnsr/commands/add.py`、`rm.py` | 两个命令 |
| `src/cnsr/assets/worker/handler.js`、`worker.js` | 控制端（计划一范围） |
| `src/cnsr/assets/node/*.sh` | 服务器端脚本 |
| `src/cnsr/assets/xray/compose.yml`、`config.json` | Xray 模板 |
| `tests/cnsr/`、`tests/worker/` | Python 测试；Worker 测试 |

## 对设计的三处实现调整

写计划时核实发现以下情况，按下列做法实现，并已同步改进设计文档：

- 扫描工具 — RealiTLScanner v0.2.3 的发布文件只有 linux-amd64、linux-arm64 和 windows-64，没有 macOS 版本。所以改为用 Python 自己实现同样的探测（TLS 1.3、h2、读取证书域名），不再下载二进制。
- 被墙域名 — 旧方案依赖 reality-checker 内置的黑名单。本机扫描是按 IP 连接、不带 SNI 的，挡不住按 SNI 封锁的域名。所以对初筛后的候选，再从你电脑上带 SNI 握手一次，握不上就排除。节点端验证改用 curl，不再依赖 reality-checker。
- AWS 凭据 — 先用 boto3 的默认凭据链（环境变量、`~/.aws`），都没有才询问。

### Task 1: 项目骨架与帮助菜单

**Files:**
- Modify: `pyproject.toml`
- Create: `src/cnsr/__init__.py`、`src/cnsr/cli.py`、`src/cnsr/errors.py`、`.github/workflows/ci.yml`
- Test: `tests/cnsr/test_cli.py`

**Interfaces:**
- Produces: `cnsr.__version__ = "0.2.0.dev0"`；`cnsr.cli.HELP_TEXT: str`；`cnsr.cli.parse_args(argv: list[str]) -> argparse.Namespace`（字段 `command`、`alias`、`aws`、`ip`）；`cnsr.cli.main(argv: list[str] | None = None) -> int`；`cnsr.errors.CnsrError(Exception)`（消息直接展示给用户）。
- `main` 把 `add`、`rm` 分发给 `cnsr.commands.add.run(ns) -> int`、`cnsr.commands.rm.run(ns) -> int`，用函数内延迟导入，本任务不实现这两个模块。

- [ ] **Step 1: 改 `pyproject.toml`**

去掉 `[tool.uv] package = false`，依赖改为 `boto3>=1.34`、`httpx>=0.27`、`cryptography>=43`；`[dependency-groups] dev = ["pytest>=8", "nodejs-wheel-binaries>=22"]`；`[project.scripts] cnsr = "cnsr.cli:main"`；构建后端 `uv_build>=0.13.0,<0.14`，`module-name = "cnsr"`；`[tool.pytest.ini_options] testpaths = ["tests/cnsr"]`，这样旧测试不会被默认收集。运行 `uv sync`。

- [ ] **Step 2: 写失败的测试**

```python
from cnsr import __version__
from cnsr.cli import HELP_TEXT, main, parse_args
import pytest

def test_no_args_prints_help(capsys):
    assert main([]) == 0
    assert capsys.readouterr().out == HELP_TEXT

def test_help_flag_prints_help(capsys):
    assert main(["-h"]) == 0
    out = capsys.readouterr().out
    assert "add [别名]" in out and "--aws <区域>" in out and "--ip <IP>" in out and "rm <别名>" in out

def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out == f"cnsr {__version__}\n"

def test_parse_add_aws():
    ns = parse_args(["add", "jp-1", "--aws", "jp"])
    assert (ns.command, ns.alias, ns.aws, ns.ip) == ("add", "jp-1", "jp", None)

@pytest.mark.parametrize("argv", [
    ["add", "x", "--aws", "jp", "--ip", "192.0.2.1"],
    ["add", "x", "--aws", "eu"],
    ["rm"],
])
def test_parse_rejects(argv):
    with pytest.raises(SystemExit):
        parse_args(argv)
```

- [ ] **Step 3: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_cli.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'cnsr'` 或导入失败。

- [ ] **Step 4: 实现 `cli.py`、`errors.py`、`__init__.py`**

`HELP_TEXT` 逐字复制设计文档第 1 节的代码块，末尾带一个换行。`argparse` 用 `add_help=False`，`-h`、`--help` 和无参数时打印 `HELP_TEXT`。`--aws` 的 choices 为 `jp`、`sg`、`us`，与 `--ip` 互斥。`main` 开头在 Windows 上执行 `sys.stdout.reconfigure(encoding="utf-8")`。捕获 `CnsrError` 时打印 `错误：<消息>` 并返回 1；捕获 `KeyboardInterrupt` 时打印 `已中断。修好问题后重跑同一条命令即可继续。` 并返回 130。

- [ ] **Step 5: 写 CI**

`.github/workflows/ci.yml`：在 `ubuntu-latest`、`macos-latest`、`windows-latest` 三个平台上，用 `astral-sh/setup-uv` 跑 `uv sync` 和 `uv run pytest`；只在 ubuntu 上再跑 `uv run node --test tests/worker/`。

- [ ] **Step 6: 运行，确认通过**

Run: `uv run pytest tests/cnsr/test_cli.py -v`
Expected: PASS（7 项）。

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/cnsr/__init__.py src/cnsr/cli.py src/cnsr/errors.py .github/workflows/ci.yml tests/cnsr/test_cli.py
git commit -m "feat(cli): scaffold cnsr package with help menu and argument parsing"
```

### Task 2: 本机路径与凭据文件

**Files:**
- Create: `src/cnsr/paths.py`、`src/cnsr/localconf.py`
- Test: `tests/cnsr/test_localconf.py`

**Interfaces:**
- Produces: `paths.config_dir(env: Mapping[str, str], platform: str, home: Path) -> Path`；`paths.ssh_config_path(home: Path) -> Path`；`paths.pub_dir(home: Path) -> Path`；`localconf.KEYS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ZONE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "CNSR_SSH_AGENT")`；`localconf.load(path: Path) -> dict[str, str]`；`localconf.save(path: Path, values: dict[str, str], *, platform: str = sys.platform, run=subprocess.run) -> None`。

- [ ] **Step 1: 写失败的测试**

```python
def test_config_dir_windows():
    assert paths.config_dir({"APPDATA": r"C:\Users\a\AppData\Roaming"}, "win32", Path("C:/Users/a")) == Path(r"C:\Users\a\AppData\Roaming") / "cnsr"

def test_config_dir_respects_xdg():
    assert paths.config_dir({"XDG_CONFIG_HOME": "/x"}, "linux", Path("/home/a")) == Path("/x/cnsr")

def test_config_dir_default_posix():
    assert paths.config_dir({}, "darwin", Path("/Users/a")) == Path("/Users/a/.config/cnsr")

def test_load_tolerates_crlf_bom_quotes(tmp_path):
    p = tmp_path / "secrets.env"
    p.write_bytes(b'\xef\xbb\xbfCLOUDFLARE_API_TOKEN="abc"\r\n# c\r\n\r\nCLOUDFLARE_ZONE=example.com\r\n')
    assert localconf.load(p) == {"CLOUDFLARE_API_TOKEN": "abc", "CLOUDFLARE_ZONE": "example.com"}

def test_load_missing_file_is_empty(tmp_path):
    assert localconf.load(tmp_path / "none.env") == {}

@pytest.mark.skipif(sys.platform == "win32", reason="posix permissions")
def test_save_writes_lf_and_mode_600(tmp_path):
    p = tmp_path / "secrets.env"
    localconf.save(p, {"CLOUDFLARE_ZONE": "example.com"})
    assert b"\r" not in p.read_bytes()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600

def test_save_on_windows_restricts_with_icacls(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("USERNAME", "alice")
    localconf.save(tmp_path / "s.env", {"CLOUDFLARE_ZONE": "example.com"}, platform="win32", run=lambda a, **k: calls.append(a))
    assert calls == [["icacls", str(tmp_path / "s.env"), "/inheritance:r", "/grant:r", "alice:F"]]
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_localconf.py -v`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现 `paths.py` 和 `localconf.py`**

`load` 跳过空行和 `#` 注释，去掉值两端成对的引号。`save` 先写临时文件再替换，写完后 POSIX 上 `chmod 600`，Windows 上调用 `icacls`；未知键原样保留。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr/test_localconf.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/paths.py src/cnsr/localconf.py tests/cnsr/test_localconf.py
git commit -m "feat(config): add platform paths and secrets file handling"
```

### Task 3: 交互与输出

**Files:**
- Create: `src/cnsr/ui.py`
- Test: `tests/cnsr/test_ui.py`

**Interfaces:**
- Produces: `class Ui(input_fn=input, secret_fn=getpass.getpass, out=sys.stdout, interactive: bool | None = None)`，方法：`ask(prompt: str, default: str | None = None, validate: Callable[[str], str | None] | None = None) -> str`、`secret(prompt: str) -> str`、`choose(prompt: str, options: list[str]) -> int`（返回 0 起的序号）、`confirm_text(prompt: str, expected: str) -> None`、`step(i: int, n: int, title: str)`、`info(msg)`、`warn(msg)`。`interactive` 为 None 时取 `sys.stdin.isatty()`；非交互模式下 `ask`、`secret`、`choose`、`confirm_text` 抛 `CnsrError(f"缺少参数：{prompt}")`。

- [ ] **Step 1: 写失败的测试**

```python
def make(inputs, interactive=True):
    it = iter(inputs); out = io.StringIO()
    return Ui(input_fn=lambda p: next(it), secret_fn=lambda p: next(it), out=out, interactive=interactive), out

def test_ask_uses_default_on_empty():
    ui, _ = make([""]); assert ui.ask("登录用户", default="root") == "root"

def test_ask_repeats_until_valid():
    ui, out = make(["bad", "ok"])
    assert ui.ask("别名", validate=lambda s: None if s == "ok" else "格式不对") == "ok"
    assert "格式不对" in out.getvalue()

def test_choose_returns_index():
    ui, _ = make(["3", "2"]); assert ui.choose("区域", ["jp", "sg"]) == 1

def test_confirm_text_loops_until_exact():
    ui, _ = make(["保存", "已保存"]); ui.confirm_text("存好后输入“已保存”", "已保存")

def test_noninteractive_raises():
    ui, _ = make([], interactive=False)
    with pytest.raises(CnsrError, match="缺少参数：别名"):
        ui.ask("别名")
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_ui.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `ui.py`**

`choose` 列出 `1. xxx` 形式的选项，输入越界时重问。`step` 输出 `[i/n] 标题`。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr/test_ui.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/ui.py tests/cnsr/test_ui.py
git commit -m "feat(ui): add interactive prompts with non-interactive guard"
```

### Task 4: Cloudflare 客户端、KV 与 DNS

**Files:**
- Create: `src/cnsr/cloudflare/__init__.py`、`api.py`、`kv.py`、`dns.py`
- Test: `tests/cnsr/test_cloudflare.py`

**Interfaces:**
- Produces:
  - `class CloudflareError(Exception)`，属性 `status: int`、`messages: list[str]`。
  - `class CloudflareClient(token: str, transport: httpx.BaseTransport | None = None)`：`request(method: str, path: str, *, params=None, json=None, files=None, raw: bool = False) -> Any`。基址 `https://api.cloudflare.com/client/v4`；默认返回响应体的 `result`；`raw=True` 返回 `httpx.Response`，用于 KV 值。`zone(name: str) -> dict`，返回 `{"id": ..., "account": {"id": ...}}`。
  - `class KvStore(cf: CloudflareClient, account_id: str, namespace_id: str)`：`get(key) -> str | None`（404 返回 None）、`put(key, value: str)`、`delete(key)`、`keys(prefix: str) -> list[str]`（处理分页游标）。
  - `dns.upsert_record(cf, zone_id: str, name: str, rtype: Literal["A", "AAAA"], content: str) -> str`，返回记录 id；`dns.delete_record(cf, zone_id: str, record_id: str) -> None`；`dns.public_resolves(name: str, rtype: str, expected: set[str], transport=None) -> bool`；`dns.local_resolves(name: str, expected: set[str]) -> bool`。

- [ ] **Step 1: 写失败的测试**（用 `httpx.MockTransport` 记录请求）

```python
def test_request_sends_bearer_and_unwraps_result(): ...
    # assert request.headers["authorization"] == "Bearer t"; returns body["result"]

def test_request_raises_on_failure(): ...
    # {"success": false, "errors": [{"message": "Authentication error"}]}, 403 -> CloudflareError(status=403, messages=["Authentication error"])

def test_kv_get_missing_returns_none(): ...   # 404 -> None

def test_upsert_creates_grey_record_with_ttl_60(): ...
    # GET dns_records?type=A&name=edge-cache-v123.example.com -> []; then POST body == {"type": "A", "name": "edge-cache-v123.example.com", "content": "192.0.2.10", "ttl": 60, "proxied": False}

def test_upsert_patches_changed_content(): ...   # existing content 192.0.2.9 -> PATCH {"content": "192.0.2.10"}, returns existing id

def test_upsert_keeps_same_content_without_write(): ...   # only GET issued

def test_delete_record_tolerates_404(): ...

def test_public_resolves_compares_answer_set(): ...
    # DoH GET https://cloudflare-dns.com/dns-query?name=..&type=A with accept: application/dns-json; Answer data {"192.0.2.10"} -> True; {"192.0.2.9"} -> False
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_cloudflare.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `api.py`、`kv.py`、`dns.py`**

KV 值的路径为 `/accounts/{a}/storage/kv/namespaces/{n}/values/{key}`，`key` 需要 URL 编码。`local_resolves` 用 `socket.getaddrinfo`，比较解析结果是否包含全部 `expected`。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr/test_cloudflare.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/cloudflare tests/cnsr/test_cloudflare.py
git commit -m "feat(cloudflare): add api client, kv store and dns helpers"
```

### Task 5: 控制端 Worker（计划一范围）

**Files:**
- Create: `src/cnsr/assets/worker/handler.js`、`src/cnsr/assets/worker/worker.js`
- Test: `tests/worker/handler.test.mjs`

**Interfaces:**
- Produces:
  - `handler.js` 导出 `makeHandler({ connect }) -> (request, env) => Promise<Response>`。KV 绑定名为 `CNSR`。
  - `worker.js` 为 `import { connect } from "cloudflare:sockets"`，`export default { fetch: makeHandler({ connect }) }`。
  - KV 键：`meta:control` 存 JSON `{"host", "zone", "client_token", "admin_token"}`；`node:<alias>` 存节点 JSON，其中 `line` 字段是圈X 节点行（见 Task 6）。
  - 路由：
    - `GET /<client_token>/cnsr.snippet` — 按别名排序，输出所有节点的 `line`，每行一个，末尾带换行；`content-type: text/plain; charset=utf-8`，`cache-control: no-store`。
    - `POST /admin/probe` — 需要 `Authorization: Bearer <admin_token>`；请求体 `{"host": "<IPv4 或 IPv6 字面量>", "port": 443}`；5 秒内连上返回 `{"ok": true, "ms": <int>, "error": null}`，否则返回 `{"ok": false, "ms": null, "error": "<文字>"}`。
    - `meta:control` 缺失或缺少任一 token 时一律返回 503；客户端 token 不对返回 404；管理 token 不对返回 401；host 不是 IP 字面量返回 400。

- [ ] **Step 1: 写失败的测试**

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { makeHandler } from "../../src/cnsr/assets/worker/handler.js";

const meta = { host: "c.example.com", zone: "example.com", client_token: "ct", admin_token: "at" };
function kv(entries) { /* Map-backed get(key) and list({prefix, cursor}) -> {keys:[{name}], list_complete:true} */ }

test("503 when meta missing", async () => { /* status 503 */ });
test("snippet lists lines sorted by alias", async () => {
  // node:b line "B", node:a line "A" -> body "A\nB\n"
});
test("snippet with wrong token is 404", async () => {});
test("probe requires admin bearer", async () => { /* no header -> 401; "Bearer ct" -> 401 */ });
test("probe reports open port", async () => { /* fake connect().opened resolves -> ok true, ms is number */ });
test("probe reports failure", async () => { /* opened rejects -> ok false, error string */ });
test("probe rejects hostnames", async () => { /* host "example.com" -> 400 */ });
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run node --test tests/worker/`
Expected: FAIL，找不到模块。

- [ ] **Step 3: 实现 `handler.js` 和 `worker.js`**

token 比较用逐字节、不提前退出的写法。探测时 `Promise.race` 等待 `socket.opened` 和 5 秒超时，完成后无论结果都调用 `socket.close()`。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run node --test tests/worker/`
Expected: PASS（7 项）。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/assets/worker tests/worker
git commit -m "feat(worker): serve node snippet and external port probe"
```

### Task 6: 控制端部署与节点清单

**Files:**
- Create: `src/cnsr/naming.py`、`src/cnsr/state.py`、`src/cnsr/cloudflare/control.py`
- Test: `tests/cnsr/test_state.py`、`tests/cnsr/test_control.py`

**Interfaces:**
- Consumes: Task 4 的 `CloudflareClient`、`KvStore`。
- Produces:
  - `naming.random_label(rng: random.Random) -> str`，格式匹配 `^[a-z]+-[a-z]+-v\d{3}$`，两个词不同，词表为 `("edge", "cache", "static", "media", "assets", "cdn", "api", "sync", "files", "metrics", "gateway", "data")`。`naming.validate_alias(s: str) -> str | None`，用 `^[a-z0-9][a-z0-9_-]{0,31}$`，不合法时返回中文错误信息。
  - `state.py` 的 dataclass：`SshInfo(user: str, port: int, key_name: str)`、`XrayInfo(uuid: str, public_key: str, short_id: str, sni: str, dest_ip: str)`、`Node(alias, source: Literal["aws", "vps"], ipv4: str, ipv6: str | None = None, region: str | None = None, instance_name: str | None = None, static_ip_name: str | None = None, domain: str | None = None, dns_record_ids: dict[str, str] = field(default_factory=dict), ssh: SshInfo | None = None, xray: XrayInfo | None = None, node_token: str | None = None, line: str | None = None)`，带 `to_json() -> str` 和 `Node.from_json(s) -> Node`；`ControlMeta(host: str, zone: str, client_token: str, admin_token: str)`；`class Inventory(kv: KvStore)`，方法 `get(alias) -> Node | None`、`put(node)`、`delete(alias)`、`list() -> list[Node]`、`meta() -> ControlMeta | None`、`put_meta(meta)`。
  - `control.WORKER_NAME = "cnsr-control"`、`KV_TITLE = "cnsr-control"`、`COMPAT_DATE = "2026-09-01"`。
  - `control.check_token(cf, zone_name: str) -> list[str]`，返回缺失权限的中文名，取值来自 `{"读取域名", "编辑 DNS", "编辑 Workers 脚本", "编辑 Workers KV", "绑定 Workers 自定义域名"}`。
  - `control.ensure_control_plane(cf, zone_name: str, rng: random.Random) -> tuple[KvStore, ControlMeta, str]`，第三项为 zone_id。
  - `@dataclass ProbeResult(ok: bool, ms: int | None, error: str | None)`；`control.probe(meta, host: str, port: int = 443, transport=None) -> ProbeResult`。

- [ ] **Step 1: 写失败的测试**

```python
def test_random_label_format():
    rng = random.Random(1)
    for _ in range(50):
        assert re.fullmatch(r"[a-z]+-[a-z]+-v\d{3}", naming.random_label(rng))

@pytest.mark.parametrize("alias,ok", [("jp-1", True), ("us_1", True), ("Jp", False), ("-a", False), ("a" * 33, False)])
def test_validate_alias(alias, ok):
    assert (naming.validate_alias(alias) is None) == ok

def test_node_json_round_trip():
    n = Node(alias="jp-1", source="aws", ipv4="192.0.2.10", ipv6="2001:db8::10", region="jp",
             ssh=SshInfo("admin", 22, "jp-1"), xray=XrayInfo("u", "pk", "0123456789abcdef", "www.example.com", "198.51.100.7"))
    assert Node.from_json(n.to_json()) == n

def test_inventory_list_sorted(fake_kv): ...   # puts b then a -> list aliases ["a", "b"]; keys "node:a", "node:b"

def test_check_token_reports_missing_workers(mock_cf): ...   # 403 on GET /accounts/{a}/workers/scripts -> ["编辑 Workers 脚本"]

def test_ensure_control_plane_fresh_account(mock_cf): ...
    # creates KV namespace titled "cnsr-control"; PUT /accounts/{a}/workers/scripts/cnsr-control multipart with metadata
    # {"main_module": "worker.js", "compatibility_date": "2026-09-01", "bindings": [{"type": "kv_namespace", "name": "CNSR", "namespace_id": ns}]}
    # and parts worker.js + handler.js; PUT /accounts/{a}/workers/domains {"environment": "production", "hostname": meta.host, "service": "cnsr-control", "zone_id": z}
    # meta written to KV key "meta:control"; meta.host ends with ".example.com"

def test_ensure_control_plane_adopts_existing(mock_cf): ...
    # namespace and meta:control already exist -> same tokens returned, no namespace POST, script still uploaded

def test_probe_posts_bearer(): ...   # POST https://c.example.com/admin/probe with Authorization "Bearer at", body {"host": "2001:db8::10", "port": 443}
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_state.py tests/cnsr/test_control.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `naming.py`、`state.py`、`control.py`**

`ensure_control_plane` 的顺序：取 zone 和 account id → 按标题找或建 KV 命名空间 → 读 `meta:control`，没有就生成（`host = f"{random_label(rng)}.{zone}"`，两个 token 用 `secrets.token_urlsafe(24)`）→ 每次都上传 Worker 源码（用 `importlib.resources` 读取 `cnsr/assets/worker/*.js`，两部分的 content-type 为 `application/javascript+module`）→ 绑定自定义域名 → 最后写 `meta:control`。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr/test_state.py tests/cnsr/test_control.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/naming.py src/cnsr/state.py src/cnsr/cloudflare/control.py tests/cnsr/test_state.py tests/cnsr/test_control.py
git commit -m "feat(control): deploy or adopt control plane and store inventory in kv"
```

### Task 7: SSH agent 与 SSH 别名

**Files:**
- Create: `src/cnsr/ssh/__init__.py`、`agent.py`、`config.py`
- Test: `tests/cnsr/test_ssh_agent.py`、`tests/cnsr/test_ssh_config.py`

**Interfaces:**
- Produces:
  - `@dataclass AgentKey(line: str, comment: str)`。
  - `agent.detect_agents(env: Mapping[str, str], home: Path, platform: str, exists=os.path.exists) -> list[str | None]`。Windows 返回 `[None]`，表示使用默认的命名管道。其他平台依次检查：Bitwarden（macOS 为 `~/Library/Containers/com.bitwarden.desktop/Data/.bitwarden-ssh-agent.sock`，Linux 为 `~/.bitwarden-ssh-agent.sock`）、1Password（macOS 为 `~/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock`，Linux 为 `~/.1password/agent.sock`）、`SSH_AUTH_SOCK`。只保留存在的路径，并去重。
  - `agent.list_keys(agent: str | None, run=subprocess.run) -> list[AgentKey]`，执行 `ssh-add -L`，退出码 1 视为空列表。
  - `agent.find_key(keys, name) -> AgentKey | None`，按注释精确匹配。
  - `agent.ensure_pub_file(key: AgentKey, name: str, pub_dir: Path) -> Path`。
  - `@dataclass HostBlock(alias: str, hostname: str, user: str, port: int, identity_file: str, identity_agent: str | None)`。
  - `config.read_block(path: Path, alias: str) -> HostBlock | None`、`config.write_block(path: Path, block: HostBlock) -> None`、`config.remove_block(path: Path, alias: str) -> bool`。

- [ ] **Step 1: 写失败的测试**

```python
def test_detect_agents_macos_prefers_bitwarden(tmp_path): ...
    # bitwarden socket exists, SSH_AUTH_SOCK=/tmp/x exists -> [bw_path, "/tmp/x"]

def test_detect_agents_windows_uses_default_pipe():
    assert agent.detect_agents({}, Path("C:/Users/a"), "win32") == [None]

def test_list_keys_parses_comment():
    run = lambda args, **kw: subprocess.CompletedProcess(args, 0, "ssh-ed25519 AAAA jp-1\nssh-rsa BBBB other key\n", "")
    keys = agent.list_keys("/s", run=run)
    assert [k.comment for k in keys] == ["jp-1", "other key"]

def test_list_keys_no_identities_is_empty(): ...   # returncode 1 -> []

def test_write_block_preserves_other_blocks(tmp_path):
    p = tmp_path / "config"
    p.write_text("# mine\nHost prod\n    HostName 192.0.2.5\n\nHost jp-1\n    HostName 192.0.2.9\n")
    config.write_block(p, HostBlock("jp-1", "edge-cache-v123.example.com", "admin", 22, "~/.ssh/pub/jp-1.pub", "/a b/agent.sock"))
    text = p.read_text()
    assert text.startswith("# mine\nHost prod\n    HostName 192.0.2.5\n")
    assert '    IdentityAgent "/a b/agent.sock"\n' in text and "192.0.2.9" not in text
    assert (tmp_path / "config_bak_cnsr").read_text().count("192.0.2.9") == 1

def test_write_block_creates_missing_file(tmp_path): ...
def test_read_block_ignores_multi_pattern_hosts(tmp_path): ...   # "Host jp-1 other" -> None
def test_remove_block(tmp_path): ...
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_ssh_agent.py tests/cnsr/test_ssh_config.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `agent.py`、`config.py`**

Host 块从 `Host` 行开始，到下一个 `Host` 或 `Match` 行之前结束。写入的块固定为以下几行，`IdentityAgent` 只在 agent 不为 None 时写，值总是加双引号：

```text
Host <alias>
    HostName <hostname>
    User <user>
    Port <port>
    IdentityFile <identity_file>
    IdentitiesOnly yes
    IdentityAgent "<agent>"
```

写入前把原文件复制为同目录的 `config_bak_cnsr`。不动的行按原样保留，包括它们原来的换行符。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr/test_ssh_agent.py tests/cnsr/test_ssh_config.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/ssh tests/cnsr/test_ssh_agent.py tests/cnsr/test_ssh_config.py
git commit -m "feat(ssh): detect agents, pick keys and edit ssh config host blocks"
```

### Task 8: SSH 远程执行

**Files:**
- Create: `src/cnsr/ssh/remote.py`
- Test: `tests/cnsr/test_ssh_remote.py`

**Interfaces:**
- Consumes: Task 7 的 `HostBlock` 字段语义。
- Produces:
  - `@dataclass Target(alias: str, hostname: str, user: str, port: int, identity_file: str | None, identity_agent: str | None)`。
  - `class SshError(CnsrError)`，属性 `kind: Literal["port", "key", "password", "hostkey", "other"]`；消息为下表的中文提示。
  - `remote.classify(stderr: str) -> str`。
  - `class Remote(target: Target, ssh_config: Path, run=subprocess.run)`：`run(command: list[str], *, input: str | None = None, sudo: bool = False, timeout: int = 600) -> str`（返回 stdout，退出码 255 抛 `SshError`，其他非零退出码抛 `CnsrError`）；`run_script(name: str, args: list[str], *, sudo: bool = True) -> str`（读取 `cnsr/assets/node/<name>`，作为 `bash -s -- args` 的标准输入）；`put_text(path: str, content: str, mode: str = "600") -> None`（内容经 `run(..., input=content)` 写入，不经过脚本）；`can_login() -> bool`。
  - 脚本经标准输入下发时，脚本里的命令读标准输入会读到脚本正文。所以服务器端脚本一律不读标准输入，数据都走参数；只有 `chpasswd` 这类单条命令才用 `run(..., input=...)` 传数据。
  - `remote.install_key_with_password(target: Target, pubkey_line: str, ssh_config: Path, run=subprocess.run) -> None`。
  - `remote.forget_host_key(hostname: str, port: int, run=subprocess.run) -> None`。

| kind | 识别依据（stderr 包含） | 提示 |
| :--- | :--- | :--- |
| port | `Connection refused`、`timed out`、`No route to host`、`Could not resolve hostname` | 连不上 SSH 端口：检查 IP、端口和厂商防火墙 |
| key | `Permission denied (publickey` | 密钥被拒：确认公钥已装到服务器、agent 已解锁 |
| password | `Permission denied, please try again`、`Permission denied (password` | 密码错误：cnsr 不会自动重试，确认后重跑 |
| hostkey | `REMOTE HOST IDENTIFICATION HAS CHANGED`、`Host key verification failed` | 主机指纹不符：如果刚重装过系统，可以删除旧指纹后重试 |

- [ ] **Step 1: 写失败的测试**

```python
T = Target("jp-1", "192.0.2.10", "root", 22, "~/.ssh/pub/jp-1.pub", None)

def test_run_builds_safe_args(tmp_path):
    seen = {}
    def run(args, **kw):
        seen["args"] = args; return subprocess.CompletedProcess(args, 0, "ok", "")
    Remote(T, tmp_path / "config", run=run).run(["echo", "a b"], sudo=True)
    a = seen["args"]
    assert a[0] == "ssh" and a[-2] == "jp-1" and a[-1] == "sudo -n echo 'a b'"
    for opt in ("BatchMode=yes", "ControlMaster=no", "StrictHostKeyChecking=accept-new", "HostName=192.0.2.10", "Port=22", "User=root", "IdentitiesOnly=yes"):
        assert opt in a

@pytest.mark.parametrize("stderr,kind", [
    ("ssh: connect to host 192.0.2.10 port 22: Connection refused", "port"),
    ("Permission denied (publickey).", "key"),
    ("Permission denied, please try again.", "password"),
    ("@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @", "hostkey"),
    ("kex_exchange_identification: read: Connection reset by peer", "other"),
])
def test_classify(stderr, kind):
    assert classify(stderr) == kind

def test_run_raises_ssh_error_on_255(tmp_path): ...   # returncode 255 + "Permission denied (publickey)." -> SshError(kind="key")
def test_run_script_streams_asset(tmp_path): ...       # input == the asset text exactly; command ends with "sudo -n bash -s -- 23456"
def test_install_key_with_password_disables_pubkey(tmp_path): ...
    # args contain "BatchMode=no", "PubkeyAuthentication=no", "PreferredAuthentications=password,keyboard-interactive"; input == pubkey_line + "\n"
def test_forget_host_key_non_default_port():
    calls = []; forget_host_key("192.0.2.10", 2222, run=lambda a, **k: calls.append(a))
    assert calls == [["ssh-keygen", "-R", "[192.0.2.10]:2222"]]
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_ssh_remote.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `remote.py`**

远程命令用 `shlex.join` 拼成一个参数。`sudo=True` 时加 `sudo -n` 前缀，登录用户是 root 时不加。`install_key_with_password` 在远端执行 `umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys`，密码由 OpenSSH 自己从终端读取。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr/test_ssh_remote.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/ssh/remote.py tests/cnsr/test_ssh_remote.py
git commit -m "feat(ssh): run remote scripts and classify connection failures"
```

### Task 9: 动手前体检

**Files:**
- Create: `src/cnsr/assets/node/preflight.sh`、`src/cnsr/server/__init__.py`、`src/cnsr/server/preflight.py`
- Test: `tests/cnsr/test_preflight.py`、`tests/cnsr/test_node_scripts.py`

**Interfaces:**
- Produces:
  - `preflight.sh <ssh_port>` 输出 `key=value` 行，键为：`os_id`、`os_version`、`arch`、`user`、`listen`（可重复，值如 `0.0.0.0:22`、`[::]:443`）、`containers`、`fw`（可重复，ufw 启用时每条规则一行，nftables 或 iptables 里有非默认规则时各一行摘要）、`admin_exists`（`0` 或 `1`）、`port_line`（可重复，`/etc/ssh/sshd_config` 里未注释的 `Port` 行）、`ipv6`（第一个全局地址，没有就留空）。
  - `@dataclass Facts(...)`，字段与上面的键一一对应，可重复的键为 `list[str]`。
  - `preflight.parse_facts(text: str) -> Facts`。
  - `preflight.evaluate(f: Facts, *, ssh_port: int, will_harden: bool) -> list[str]`，返回中文发现列表，空列表表示可以接管。
  - `SUPPORTED = {("debian", "12"), ("debian", "13"), ("ubuntu", "22.04"), ("ubuntu", "24.04")}`，架构只接受 `x86_64`。

| 发现 | 条件 | 文案 |
| :--- | :--- | :--- |
| 系统不支持 | `(os_id, os_version)` 不在 SUPPORTED，或 arch 不是 x86_64 | `不支持的系统：{os_id} {os_version} {arch}（只支持 Debian 12、13 和 Ubuntu 22.04、24.04，x86-64）` |
| 443 被占用 | 任一 listen 的端口为 443 | `443 端口已被占用` |
| 其他服务 | 非回环地址上的监听端口既不是 ssh_port 也不是 443 | `除 SSH 外还有其他服务在监听：{端口列表}` |
| 已有容器 | containers > 0 | `已有 {n} 个容器在运行` |
| 已有防火墙 | 存在只放行 ssh_port 以外的规则 | `已有防火墙规则：{规则摘要}` |
| admin 已存在 | will_harden 且 admin_exists | `用户 admin 已存在` |
| 端口写死 | will_harden 且有 port_line | `sshd_config 里写死了 SSH 端口，无法安全地改端口` |

- [ ] **Step 1: 写失败的测试**

```python
CLEAN = "os_id=debian\nos_version=12\narch=x86_64\nuser=root\nlisten=0.0.0.0:22\nlisten=[::]:22\nlisten=127.0.0.53:53\ncontainers=0\nadmin_exists=0\nipv6=2001:db8::10\n"

def test_clean_server_has_no_findings():
    assert evaluate(parse_facts(CLEAN), ssh_port=22, will_harden=True) == []

def test_parse_repeated_keys():
    f = parse_facts(CLEAN); assert f.listen == ["0.0.0.0:22", "[::]:22", "127.0.0.53:53"] and f.ipv6 == "2001:db8::10"

@pytest.mark.parametrize("extra,needle", [
    ("listen=0.0.0.0:443\n", "443 端口已被占用"),
    ("listen=0.0.0.0:8080\n", "除 SSH 外还有其他服务在监听：8080"),
    ("fw=ALLOW 3306/tcp\n", "已有防火墙规则"),
    ("port_line=Port 22\n", "写死了 SSH 端口"),
])
def test_findings(extra, needle):
    out = evaluate(parse_facts(CLEAN.replace("containers=0\n", "containers=0\n" + extra)), ssh_port=22, will_harden=True)
    assert any(needle in s for s in out)

def test_containers_finding(): ...   # containers=2 -> "已有 2 个容器在运行"
def test_unsupported_os(): ...       # os_version=11 -> "不支持的系统"
def test_aws_skips_harden_only_checks(): ...   # admin_exists=1 with will_harden=False -> []
```

`tests/cnsr/test_node_scripts.py`：遍历 `src/cnsr/assets/node/*.sh`，对每个文件运行 `bash -n`，期望退出码为 0；Windows 上跳过。以后各任务新增的脚本自动纳入。

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_preflight.py tests/cnsr/test_node_scripts.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `preflight.sh` 和 `preflight.py`**

脚本只读，不改任何东西：用 `/etc/os-release`、`uname -m`、`id -un`、`ss -Htln`、`docker ps -q`（没装 docker 时为 0）、`ufw status`、`nft list ruleset`、`iptables-save`、`id admin`、`ip -6 addr show scope global`。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr/test_preflight.py tests/cnsr/test_node_scripts.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/assets/node/preflight.sh src/cnsr/server tests/cnsr/test_preflight.py tests/cnsr/test_node_scripts.py
git commit -m "feat(server): add read-only preflight and takeover rules"
```

### Task 10: AWS Lightsail

**Files:**
- Create: `src/cnsr/aws/__init__.py`、`fingerprint.py`、`lightsail.py`
- Test: `tests/cnsr/test_fingerprint.py`、`tests/cnsr/test_lightsail.py`

**Interfaces:**
- Produces:
  - `fingerprint.lightsail_fingerprint(pub_line: str) -> str`。ED25519 为 `base64(sha256(ssh 公钥 blob))`，保留 `=` 填充；RSA 为 PKCS#1 DER 公钥的 MD5，以冒号分隔的小写十六进制表示。其他类型抛 `CnsrError`。
  - `lightsail.REGIONS = {"jp": "ap-northeast-1", "sg": "ap-southeast-1", "us": "us-west-2"}`、`BUNDLE = "nano_3_0"`、`BLUEPRINTS = ("debian_13", "debian_12")`、`LOGIN_USER = "admin"`。
  - `class KeyConflict(CnsrError)`。
  - `class Lightsail(region_code: str, client=None, sleep=time.sleep)`，方法：
    - `ensure_key_pair(name: str, pub_line: str) -> str`，返回实际使用的 key pair 名。
    - `pick_blueprint() -> str`。
    - `ensure_instance(name: str, key_pair: str) -> None`。
    - `wait_running(name: str, timeout: int = 300) -> None`。
    - `ensure_static_ip(instance: str, ip_name: str) -> str`，返回 IPv4。
    - `instance_ipv6(name: str) -> str | None`。
    - `set_firewall(name: str) -> None`。
    - `delete(instance: str, ip_name: str) -> list[str]`，返回中文错误列表。

- [ ] **Step 1: 写失败的测试**

```python
ED = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIo7AzJ6hUbdKjvRHnfzobGdGutxQzBQvznMqqchhTB+ cnsr-test-ed"
RSA = ("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC6RcZSr2/zxZn59LXnuZQo+tD0VaBrHzTUfQFtRg/uCyL4/TZbqmhGNAicSw5zz+x9RK+gAJEPmdPQOJ67DRlzexSdou7hJ0UzIOve+SQzN0+YE0m6PHQXSXMXvyKW+75J3LxZNDmdwk5BqjjiZBrE0cMF/knf4+DrkxSYbUzIqglCrUIjFFdJh77onivcV+aZI49tWp7o6bpJwZSqUmSx0ZGK7E5dNgHaAMGN/ldAgudZFXluSG87q6Gpn3MDaRTFyneopF5EzxZCW2xAT0XtWV44DRNC0xmkSkxYMTrh5asLZu5Anb9vtp4BNiEQUth+TdXk6MGigIZnHc61X4U/ cnsr-test-rsa")

def test_ed25519_fingerprint():
    assert lightsail_fingerprint(ED) == "2IZtFwdxhZ3nbHbghrVzYOP0XY2qpUD7zCslpLZwiRA="

def test_rsa_fingerprint():
    assert lightsail_fingerprint(RSA) == "d9:22:47:df:92:50:03:41:66:be:ca:e9:10:1e:f8:f6"
```

`tests/cnsr/test_lightsail.py` 用 `botocore.stub.Stubber`：

```python
def test_reuses_key_pair_with_same_fingerprint_any_name(): ...
    # get_key_pairs -> [{"name": "old-key", "fingerprint": "2IZt...iRA="}] -> returns "old-key", no import_key_pair
def test_same_name_different_fingerprint_conflicts(): ...   # name "jp-1" fingerprint "x" -> KeyConflict
def test_imports_when_missing(): ...   # import_key_pair(keyPairName="jp-1", publicKeyBase64=ED)
def test_pick_blueprint_prefers_debian_13(): ...   # get_blueprints lists both -> "debian_13"; only debian_12 -> "debian_12"
def test_ensure_instance_creates_dualstack(): ...
    # create_instances(instanceNames=["jp-1"], availabilityZone="ap-northeast-1a", blueprintId="debian_13", bundleId="nano_3_0",
    #                  keyPairName="jp-1", ipAddressType="dualstack", tags=[{"key": "cnsr", "value": "jp-1"}])
def test_ensure_instance_reuses_tagged(): ...   # get_instance returns tags cnsr=jp-1 -> no create_instances
def test_ensure_instance_refuses_untagged(): ...   # existing without tag -> CnsrError containing "同名实例"
def test_set_firewall_exact_ports(): ...
    # put_instance_public_ports(instanceName="jp-1", portInfos=[
    #   {"fromPort": 22, "toPort": 22, "protocol": "tcp", "cidrs": ["0.0.0.0/0"], "ipv6Cidrs": ["::/0"]},
    #   {"fromPort": 443, "toPort": 443, "protocol": "tcp", "cidrs": ["0.0.0.0/0"], "ipv6Cidrs": ["::/0"]},
    #   {"fromPort": 443, "toPort": 443, "protocol": "udp", "cidrs": ["0.0.0.0/0"], "ipv6Cidrs": ["::/0"]}])
def test_delete_continues_after_error(): ...   # release_static_ip raises -> delete_instance still called; returns 1 error
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_fingerprint.py tests/cnsr/test_lightsail.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `fingerprint.py`、`lightsail.py`**

RSA 用 `cryptography` 的 `load_ssh_public_key(...).public_bytes(Encoding.DER, PublicFormat.PKCS1)`。可用区取 `get_regions(includeAvailabilityZones=True)` 中第一个状态为 `available` 的。`get_instance` 抛 `NotFoundException` 时视为不存在。`wait_running` 每 5 秒查一次 `get_instance_state`。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr/test_fingerprint.py tests/cnsr/test_lightsail.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/aws tests/cnsr/test_fingerprint.py tests/cnsr/test_lightsail.py
git commit -m "feat(aws): manage lightsail instances, static ips, key pairs and firewall"
```

### Task 11: 加固与 AWS 基线

**Files:**
- Create: `src/cnsr/assets/node/harden-stage.sh`、`harden-cut.sh`、`harden-revert.sh`、`baseline-check.sh`；`src/cnsr/server/harden.py`、`src/cnsr/server/baseline.py`
- Test: `tests/cnsr/test_harden.py`、`tests/cnsr/test_baseline.py`

**Interfaces:**
- Consumes: Task 8 的 `Remote`、`Target`；Task 3 的 `Ui`。
- Produces:
  - `harden.pick_ssh_port(rng, busy: set[int]) -> int`，范围 20000–59999。
  - `harden.console_password(rng) -> str`，20 个字符，字母表为 `abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789`。
  - `class Hardener(root: Remote, make_remote: Callable[[str, int], Remote], ui: Ui, rng, sleep=time.sleep)`；`run(pubkey_line: str, busy_ports: set[int]) -> tuple[str, int]`，返回新的用户和端口，即 `("admin", port)`。
  - `baseline.parse_sshd_t(text: str) -> dict[str, str]`；`baseline.findings(sshd: dict[str, str]) -> list[str]`。要求 `passwordauthentication` 为 `no`、`kbdinteractiveauthentication` 为 `no`、`permitrootlogin` 不为 `yes`，否则返回中文发现。
- 服务器端脚本：
  - `harden-stage.sh <new_port> <pubkey_line>` — 建用户 `admin`，写入公钥，`/etc/sudoers.d/90-cnsr-admin` 设免密 sudo（先用 `visudo -cf` 校验）。安装 `ufw fail2ban python3-systemd unattended-upgrades`。写 `/etc/ssh/sshd_config.d/10-cnsr.conf`，内容为 `Port 22` 和 `Port <new_port>`。ufw 放行 `22/tcp`、`<new_port>/tcp`、`443/tcp`、`443/udp`，默认拒绝入站后启用。fail2ban 写 `/etc/fail2ban/jail.d/cnsr.local`（`[sshd]`、`enabled = true`、`port = <new_port>`、`backend = systemd`）。写 `/etc/apt/apt.conf.d/20auto-upgrades`。用 `sshd -t` 校验后重启 SSH。脚本可以重复执行。
  - `harden-cut.sh <new_port>` — 第一步必须是 `systemd-run --unit=cnsr-ssh-revert --on-active=180 /usr/local/sbin/cnsr-harden-revert stage`，然后才写最终的 drop-in（`Port <new_port>`、`PermitRootLogin no`、`PasswordAuthentication no`、`KbdInteractiveAuthentication no`），执行 `ufw delete allow 22/tcp` 并重启 SSH。
  - `harden-revert.sh stage|all` — 由 stage 脚本安装为 `/usr/local/sbin/cnsr-harden-revert`。`stage` 恢复为双端口 drop-in 并重新放行 22；`all` 删除 drop-in、禁用 ufw、删除 jail。两种模式都在 `sshd -t` 通过后重启 SSH。
  - 重启 SSH 的写法：`ssh.socket` 处于活动状态时执行 `systemctl daemon-reload && systemctl restart ssh.socket`，否则执行 `systemctl restart ssh`。
  - `baseline-check.sh` — 安装并启用 unattended-upgrades，然后输出 `sshd -T`。

- [ ] **Step 1: 写失败的测试**

```python
def test_hardener_happy_path_order(fakes):
    user, port = Hardener(fakes.root, fakes.make_remote, fakes.ui, random.Random(1)).run(PUB, busy_ports={22})
    assert user == "admin" and 20000 <= port <= 59999
    assert fakes.log == ["stage", f"login admin:{port}", "confirm 已保存", "chpasswd", "cut", f"login admin:{port}", "disarm", "sshd -T"]

def test_reverts_all_when_new_login_fails_before_cut(fakes):
    fakes.login_ok = [False]
    with pytest.raises(CnsrError, match="已回滚"):
        Hardener(...).run(PUB, busy_ports={22})
    assert "revert all" in fakes.log and "cut" not in fakes.log

def test_waits_for_timer_when_login_fails_after_cut(fakes):
    fakes.login_ok = [True, False]
    with pytest.raises(CnsrError, match="3 分钟内自动恢复"):
        Hardener(...).run(PUB, busy_ports={22})
    assert "disarm" not in fakes.log

def test_cut_arms_revert_timer_before_touching_ports():
    text = files("cnsr.assets.node").joinpath("harden-cut.sh").read_text()
    assert text.index("systemd-run --unit=cnsr-ssh-revert --on-active=180") < text.index("10-cnsr.conf") < text.index("ufw delete allow 22/tcp")

def test_pick_ssh_port_avoids_busy(): ...
def test_console_password_alphabet(): ...   # len 20, no char in "0O1lI"
```

```python
def test_baseline_ok_with_prohibit_password():
    assert findings({"passwordauthentication": "no", "kbdinteractiveauthentication": "no", "permitrootlogin": "prohibit-password"}) == []

def test_baseline_flags_password_login():
    assert findings({"passwordauthentication": "yes", "kbdinteractiveauthentication": "no", "permitrootlogin": "no"}) == ["SSH 允许密码登录"]
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_harden.py tests/cnsr/test_baseline.py tests/cnsr/test_node_scripts.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现四个脚本和 `harden.py`、`baseline.py`**

`Hardener.run` 的顺序：stage → 用新端口和 `admin` 登录并执行 `sudo -n true` → 显示控制台密码，`confirm_text("存进密码管理器后输入“已保存”", "已保存")` → 通过 `chpasswd` 的标准输入设置 `admin:<密码>` → cut → 再次用新端口登录 → `systemctl stop cnsr-ssh-revert.timer` 解除定时恢复 → 用 `baseline.parse_sshd_t` 核验 `port` 只剩新端口、且三项登录设置都为 `no`。cut 之前的任何失败都执行 `revert all`，并抛出包含“已回滚”的错误。cut 之后登录失败时，告诉你服务器会在 3 分钟内自动恢复，等 200 秒后抛错。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr/test_harden.py tests/cnsr/test_baseline.py tests/cnsr/test_node_scripts.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/assets/node/harden-*.sh src/cnsr/assets/node/baseline-check.sh src/cnsr/server/harden.py src/cnsr/server/baseline.py tests/cnsr/test_harden.py tests/cnsr/test_baseline.py
git commit -m "feat(server): harden small-vendor hosts with verify-before-cut and timed revert"
```

### Task 12: 节点域名与 SSH 别名切换

**Files:**
- Create: `src/cnsr/deploy/__init__.py`、`src/cnsr/deploy/dns_records.py`
- Test: `tests/cnsr/test_dns_records.py`

**Interfaces:**
- Consumes: Task 4 的 `dns.*`，Task 6 的 `Node`、`naming.random_label`，Task 7 的 `config.read_block`、`write_block`。
- Produces:
  - `ensure_node_records(cf, zone_id: str, zone: str, node: Node, rng) -> None`。`node.domain` 为空时生成 `f"{random_label(rng)}.{zone}"`，有值就沿用。建 A 记录，`node.ipv6` 不为空时再建 AAAA。把记录 id 写进 `node.dns_record_ids`，键为 `"A"` 或 `"AAAA"`。
  - `drop_aaaa(cf, zone_id: str, node: Node) -> None`。
  - `delete_node_records(cf, zone_id: str, node: Node) -> list[str]`，返回中文错误列表。
  - `switch_alias_when_ready(node: Node, ssh_config: Path, can_login_via: Callable[[str], bool], resolves: Callable[[str, set[str]], bool], *, wait: int = 120, sleep=time.sleep) -> bool`。

- [ ] **Step 1: 写失败的测试**

```python
def test_creates_a_and_aaaa(fake_cf): ...   # node.ipv6 set -> upsert A and AAAA, ids stored
def test_ipv4_only_creates_a(fake_cf): ...
def test_rerun_keeps_domain(fake_cf):
    node = Node(alias="jp-1", source="aws", ipv4="192.0.2.10", domain="edge-cache-v123.example.com")
    ensure_node_records(fake_cf, "z", "example.com", node, random.Random(2))
    assert node.domain == "edge-cache-v123.example.com"
def test_drop_aaaa_removes_id(fake_cf): ...
def test_switch_times_out_without_editing(tmp_path):
    # resolves always False; sleep no-op; wait=120 -> returns False; config HostName still 192.0.2.10
def test_switch_edits_hostname_when_ready(tmp_path):
    # resolves True, can_login_via True -> returns True; read_block(...).hostname == node.domain
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_dns_records.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `dns_records.py`**

`switch_alias_when_ready` 每 10 秒检查一次：先确认本机解析结果包含节点的 IP，再确认用域名能登录。都通过才改别名的 `HostName`，超时返回 False 且不改任何东西。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr/test_dns_records.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/deploy/__init__.py src/cnsr/deploy/dns_records.py tests/cnsr/test_dns_records.py
git commit -m "feat(deploy): manage node dns records and switch ssh alias when resolvable"
```

### Task 13: 候选扫描与过滤

**Files:**
- Create: `src/cnsr/scan/__init__.py`、`ranges.py`、`egress.py`、`probe.py`、`filters.py`
- Test: `tests/cnsr/test_scan.py`、`tests/cnsr/conftest.py`（本地 TLS 测试服务器夹具）

**Interfaces:**
- Produces:
  - `ranges.scan_targets(ipv4: str) -> list[str]`：节点所在 /20 的全部地址，去掉节点自己所在的 /22，以及 /20 的网络地址和广播地址。
  - `@dataclass Egress(domestic: str | None, overseas: str | None)`。`egress.DOMESTIC_ECHO = "https://4.ipw.cn"`，返回纯文本 IPv4。`egress.OVERSEAS_ECHO = "https://1.1.1.1/cdn-cgi/trace"`，从 `ip=` 行取值。`egress.check(transport=None) -> Egress`；`egress.is_direct(e: Egress) -> bool | None`，任一为 None 时返回 None。
  - `@dataclass Hit(ip: str, domain: str, issuer: str, self_signed: bool)`。`probe.scan(ips: list[str], *, port: int = 443, concurrency: int = 64, timeout: float = 5.0) -> list[Hit]`：不带 SNI，只接受 TLS 1.3 加 ALPN h2；域名取第一个非通配符的 SAN DNS 名，没有就取非通配符的 CN，都没有则不算命中。`probe.sni_ok(ip: str, domain: str, *, port: int = 443, timeout: float = 5.0) -> bool`：带 SNI 握手，只要求 TLS 1.3。
  - `filters.DYNAMIC_DNS_SUFFIXES = ("duckdns.org", "eu.org", "qzz.io", "ddns.net", "no-ip.org", "hopto.org", "dynu.net", "freeddns.org", "nip.io", "sslip.io")`。
  - `filters.NAME_KEYWORDS = ("panel", "xui", "alist", "frp", "v2ray", "stg", "staging", "dev", "test", "demo")`，按域名中以 `.` 和 `-` 切分出的词精确匹配。
  - `filters.LOW_REP_TLDS = ("info", "click", "top", "xyz", "club", "work", "site", "vip", "live", "loan", "cc", "online", "icu", "buzz", "shop", "rest")`。
  - `filters.BIG_SITES = ("apple.com", "icloud.com", "microsoft.com", "live.com", "office.com", "bing.com", "yahoo.com", "google.com", "gstatic.com", "youtube.com", "amazon.com", "cloudflare.com", "github.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "netflix.com", "nvidia.com", "samsung.com")`，按后缀匹配。
  - `filters.basic_ok(h: Hit) -> bool`：排除自签名、签发者含 `CloudFlare Origin`、域名为 `localhost` 或 IP。`filters.reputation_ok(domain: str) -> bool`。`filters.shortlist(hits: list[Hit], limit: int = 30) -> list[Hit]`：先过滤，再按域名去重并截断。

- [ ] **Step 1: 写失败的测试**

```python
def test_scan_targets_excludes_own_22():
    t = scan_targets("203.0.113.77")
    assert len(t) == 3071 and "203.0.113.77" not in t and "203.0.115.255" not in t
    assert "203.0.116.1" in t and "203.0.127.255" not in t

def test_is_direct():
    assert is_direct(Egress("203.0.113.5", "203.0.113.5")) is True
    assert is_direct(Egress("203.0.113.5", "198.51.100.9")) is False
    assert is_direct(Egress("203.0.113.5", None)) is None

def test_probe_reads_cert_domain(tls_server):          # fixture: TLS1.3 + ALPN h2, self-signed cert SAN probe.example.com
    hits = scan(["127.0.0.1"], port=tls_server.port, timeout=2)
    assert hits == [Hit("127.0.0.1", "probe.example.com", "probe.example.com", True)]

def test_probe_skips_without_h2(tls_server_no_alpn):
    assert scan(["127.0.0.1"], port=tls_server_no_alpn.port, timeout=2) == []

def test_sni_ok(tls_server):
    assert sni_ok("127.0.0.1", "probe.example.com", port=tls_server.port, timeout=2)
    assert not sni_ok("127.0.0.1", "probe.example.com", port=1, timeout=1)

@pytest.mark.parametrize("domain,ok", [
    ("panel.fzero.qzz.io", False), ("a.duckdns.org", False), ("stg-it.com", False),
    ("shop.example.top", False), ("gateway.icloud.com", False), ("devices.example.co.jp", True),
    ("www.example-corp.co.jp", True),
])
def test_reputation(domain, ok):
    assert reputation_ok(domain) is ok

def test_basic_ok_rejects_self_signed_and_origin(): ...
def test_shortlist_dedupes_and_caps(): ...   # 40 distinct ok hits + duplicates -> 30 unique domains
```

`conftest.py` 的夹具用 `cryptography` 生成自签名证书，在线程里起 `ssl` 服务：`minimum_version = TLSv1_3`，ALPN 为 `["h2"]`；无 ALPN 的变体不设置 ALPN。

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_scan.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现四个模块**

`probe.scan` 用 `asyncio` 加信号量控制并发。`ssl` 上下文设置 `check_hostname=False`、`verify_mode=CERT_NONE`、`minimum_version=maximum_version=TLSv1_3`、ALPN `["h2"]`，证书用 `getpeercert(binary_form=True)` 取出，再交给 `cryptography.x509` 解析。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr/test_scan.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/scan tests/cnsr/test_scan.py tests/cnsr/conftest.py
git commit -m "feat(scan): probe neighbour tls sites locally and filter candidates"
```

### Task 14: 选 SNI 与 Xray 部署

**Files:**
- Create: `src/cnsr/assets/node/validate-candidates.sh`、`install-docker.sh`、`verify-reality.sh`；`src/cnsr/assets/xray/compose.yml`（复制工作区当前的 `templates/compose.yml.template` 内容，包括未提交的日志和 IPv6 改动）；`src/cnsr/assets/xray/config.json`（复制 `templates/config.json.template`）；`src/cnsr/scan/select.py`；`src/cnsr/server/xray.py`
- Test: `tests/cnsr/test_select.py`、`tests/cnsr/test_xray.py`

**Interfaces:**
- Produces:
  - `@dataclass Candidate(domain: str, ip: str, latency_ms: int)`。`select.parse_validation(text: str) -> list[Candidate]`，解析每行 `domain ip ms`，忽略格式不对的行。`select.choose(cands: list[Candidate], max_backups: int = 10) -> tuple[Candidate, list[Candidate]]`，按延迟升序排列，列表为空时抛 `CnsrError("没有候选通过节点验证，已停止，不会盲选")`。
  - `xray.XRAY_IMAGE = "ghcr.io/xtls/xray-core:26.3.27"`、`xray.NODE_DIR = "/opt/cnsr"`，节点上的文件为 `xray/compose.yml`、`xray/conf/config.json`、`backups.json`、`node.env`。
  - `xray.new_identity(rng) -> tuple[str, str]`，返回 uuid4 和 16 位十六进制的 shortId。
  - `xray.parse_x25519(text: str) -> tuple[str, str]`，返回私钥和公钥。兼容两种输出：`PrivateKey:` 加 `Password:`，以及 `Private key:` 加 `Public key:`。
  - `xray.render_config(template: dict, *, alias: str, uuid: str, private_key: str, short_id: str, sni: str, dest_ip: str) -> str`。
  - `xray.read_identity(config_text: str) -> dict`，返回键 `uuid`、`private_key`、`short_id`、`sni`、`dest_ip`。
- 服务器端脚本：
  - `validate-candidates.sh <domain> <ip> [<domain> <ip> ...]` — 对每一对执行 `curl -sS -o /dev/null --max-time 8 --resolve "$d:443:$ip" --tlsv1.3 --tls-max 1.3 --curves X25519 --http2 -w '%{http_version} %{time_appconnect}' "https://$d/"`，退出码为 0 且 http_version 为 `2` 时，输出 `domain ip 毫秒`。
  - `install-docker.sh` — `docker compose version` 能用就跳过；否则用 Docker 官方 apt 源安装 `docker-ce docker-ce-cli containerd.io docker-compose-plugin`。
  - `verify-reality.sh <uuid> <public_key> <short_id> <sni>` — 用同一镜像起一个 `--network host` 的临时客户端容器，VLESS 加 REALITY 连 `127.0.0.1:443`，flow 为 `xtls-rprx-vision`，本地 socks 端口 `127.0.0.1:10808`。然后执行 `curl --socks5-hostname 127.0.0.1:10808 --max-time 10 -s -o /dev/null -w '%{http_code}' https://www.gstatic.com/generate_204`，结果为 `204` 时退出码为 0。无论成败，最后都删除容器。

- [ ] **Step 1: 写失败的测试**

```python
def test_render_config_fills_all_placeholders():
    tpl = json.loads(files("cnsr.assets.xray").joinpath("config.json").read_text())
    out = json.loads(render_config(tpl, alias="jp-1", uuid="11111111-1111-4111-8111-111111111111", private_key="PRIV",
                                   short_id="0123456789abcdef", sni="www.example.com", dest_ip="198.51.100.7"))
    ib = out["inbounds"][0]; rs = ib["streamSettings"]["realitySettings"]
    assert ib["tag"] == "jp-1" and ib["port"] == 40443 and ib["settings"]["clients"][0]["id"].startswith("1111")
    assert rs["dest"] == "198.51.100.7:443" and rs["serverNames"] == ["www.example.com"]
    assert rs["shortIds"] == ["0123456789abcdef"] and rs["privateKey"] == "PRIV"
    assert "PLACEHOLDER" not in json.dumps(out)

@pytest.mark.parametrize("text", ["PrivateKey: aaa\nPassword: bbb\nHash32: ccc\n", "Private key: aaa\nPublic key: bbb\n"])
def test_parse_x25519(text):
    assert parse_x25519(text) == ("aaa", "bbb")

def test_read_identity_round_trip(): ...
def test_new_identity_format(): ...   # uuid version 4; re.fullmatch("[0-9a-f]{16}", sid)
```

```python
def test_choose_sorts_and_caps():
    cands = [Candidate(f"d{i}.example.com", "198.51.100.7", 100 - i) for i in range(15)]
    cur, backups = choose(cands)
    assert cur.latency_ms == 86 and len(backups) == 10 and backups[0].latency_ms == 87

def test_choose_empty_stops():
    with pytest.raises(CnsrError, match="不会盲选"):
        choose([])

def test_parse_validation_ignores_bad_lines():
    assert parse_validation("a.example.com 198.51.100.7 120\ngarbage\n") == [Candidate("a.example.com", "198.51.100.7", 120)]
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_select.py tests/cnsr/test_xray.py tests/cnsr/test_node_scripts.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现三个脚本、两个模板副本、`select.py`、`xray.py`**

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr/test_select.py tests/cnsr/test_xray.py tests/cnsr/test_node_scripts.py -v`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/assets/node/validate-candidates.sh src/cnsr/assets/node/install-docker.sh src/cnsr/assets/node/verify-reality.sh src/cnsr/assets/xray src/cnsr/scan/select.py src/cnsr/server/xray.py tests/cnsr/test_select.py tests/cnsr/test_xray.py
git commit -m "feat(xray): validate sni candidates on node and render reality config"
```

### Task 15: add 命令

**Files:**
- Create: `src/cnsr/qx.py`、`src/cnsr/deploy/context.py`、`src/cnsr/deploy/steps.py`、`src/cnsr/commands/__init__.py`、`src/cnsr/commands/add.py`
- Test: `tests/cnsr/test_qx.py`、`tests/cnsr/test_add.py`（`tests/cnsr/fakes.py` 放共用假对象）

**Interfaces:**
- Consumes: 前面所有任务的接口。
- Produces:
  - `qx.node_line(domain: str, x: XrayInfo, alias: str) -> str`，固定输出：
    `vless=<domain>:443, method=none, password=<uuid>, obfs=over-tls, obfs-host=<sni>, reality-base64-pubkey=<public_key>, reality-hex-shortid=<short_id>, vless-flow=xtls-rprx-vision, udp-relay=true, tag=<alias>`
    （不带 `fast-open`，REALITY 不能开 TFO）。
  - `qx.client_lines(meta: ControlMeta) -> str`，计划一只输出下面两段，计划二再追加检测任务：

    ```text
    [server_remote]
    https://<host>/<client_token>/cnsr.snippet, tag=cnsr, update-interval=86400, opt-parser=false, enabled=true

    [filter_local]
    host, <host>, direct
    ```

  - `@dataclass AddRequest(alias: str, source: Literal["aws", "vps"], region: str | None, ip: str | None, user: str, port: int)`。
  - `@dataclass Deps`，字段为 `ui`、`conf_path`、`ssh_config`、`pub_dir`、`make_cf`、`make_lightsail`、`make_remote`、`detect_agents`、`list_keys`、`scan`、`egress`、`sni_ok`、`probe`、`rng`、`sleep`；`deploy.context.default_deps() -> Deps`。
  - `@dataclass DeployContext(req, deps, node: Node, inventory: Inventory, cf, zone_id: str, zone: str, meta: ControlMeta, key: AgentKey, agent: str | None)`。
  - `steps.STEPS = (step_ip, step_connect, step_harden, step_scan, step_sni, step_xray, step_register)`，每一步签名为 `(ctx) -> None`，并先检查实际状态再决定是否动手；`steps.run_pipeline(ctx) -> None`。
  - `commands.add.run(ns, deps: Deps | None = None) -> int`。

各步要点：

| 步骤 | 做什么 |
| :--- | :--- |
| `step_ip` | AWS：ensure_key_pair → ensure_instance → wait_running → ensure_static_ip → set_firewall，新实例先 `forget_host_key`；VPS：用请求里的 IP。写入 `node.ipv4`、`node.ipv6`，然后 `inventory.put` |
| `step_connect` | 别名先写 IP。VPS 用 root 首次连接、密钥被拒时调用 `install_key_with_password`。主机指纹不符时询问，确认后 `forget_host_key` 再重试。运行 preflight，有发现就抛错（此时还没建解析）。之后 `ensure_node_records` |
| `step_harden` | VPS 且登录用户为 root 时运行 `Hardener`，并把别名改成 `admin` 和新端口；AWS 运行 `baseline-check.sh`，有发现就抛错，然后 set_firewall |
| `step_scan` | 节点已有 Xray 配置、且备选已满 10 个时跳过。否则 `egress.is_direct` 必须为 True（为 None 时请你确认已关闭代理），然后扫描 → `shortlist` → `sni_ok` |
| `step_sni` | 把候选经 `validate-candidates.sh` 交给节点验证 → `choose`。已有 Xray 时保留当前 SNI，只更新备选。写 `backups.json` |
| `step_xray` | `install-docker.sh`。节点已有配置就用 `read_identity` 读出身份，不重新生成；否则在节点上执行 `docker run --rm <镜像> x25519` 生成密钥，并调用 `new_identity`。上传 compose 和 config，执行 `docker compose up -d`，运行 `verify-reality.sh`。用 `probe` 测 v4，有 v6 时也测 v6，v6 不通就 `drop_aaaa` 并提示 |
| `step_register` | 节点 token 沿用已有值，没有就新生成。写 `node.line`，写节点上的 `node.env`（`CNSR_CONTROL=https://<host>`、`CNSR_NODE_TOKEN=...`，权限 600），然后 `inventory.put`。用 `public_resolves` 确认 A 和 AAAA，再 `switch_alias_when_ready` |

- [ ] **Step 1: 写失败的测试**

```python
def test_node_line_exact():
    x = XrayInfo("11111111-1111-4111-8111-111111111111", "PUB", "0123456789abcdef", "www.example.com", "198.51.100.7")
    assert node_line("edge-cache-v123.example.com", x, "jp-1") == (
        "vless=edge-cache-v123.example.com:443, method=none, password=11111111-1111-4111-8111-111111111111, "
        "obfs=over-tls, obfs-host=www.example.com, reality-base64-pubkey=PUB, reality-hex-shortid=0123456789abcdef, "
        "vless-flow=xtls-rprx-vision, udp-relay=true, tag=jp-1")

def test_client_lines(): ...   # exact two sections for host c.example.com, token ct
```

```python
def test_noninteractive_missing_alias_fails(fake_deps): ...   # Ui(interactive=False), ns alias None -> returns 1, output contains "缺少参数"
def test_first_run_saves_cloudflare_settings(fake_deps): ...   # secrets.env gets CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE
def test_pipeline_runs_steps_in_order(fake_deps): ...
def test_preflight_findings_stop_before_any_change(fake_deps):
    # preflight output contains listen=0.0.0.0:443 -> returns 1 with "443 端口已被占用";
    # no DNS upsert, no harden script, no scan, no docker install were called
def test_hostkey_mismatch_prompts_then_forgets(fake_deps):
    # first connect raises SshError(kind="hostkey"); ui answers 1 (删除旧指纹并重试) -> forget_host_key called once, then preflight runs
def test_scan_stops_when_egress_not_direct(fake_deps):
    # egress -> Egress("203.0.113.5", "198.51.100.9") -> returns 1 with "扫描前请关闭代理"; fake scan never called
def test_rerun_preserves_identity(fake_deps):
    # inventory already has node with xray; remote config.json exists -> no x25519 call; resulting node.xray.uuid unchanged
def test_success_prints_client_lines(fake_deps): ...   # output contains "[server_remote]" and the node line
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_qx.py tests/cnsr/test_add.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `qx.py`、`context.py`、`steps.py`、`commands/add.py`**

`commands/add.run` 的顺序：读 `secrets.env`。没有 Cloudflare token 时询问 token 和域名，用 `check_token` 验证，缺权限就列出并退出，验证通过后保存。然后 `ensure_control_plane`。别名取参数或询问；清单里已有就沿用记录。来源、区域、IP、登录用户和端口按设计文档第 2 节的顺序询问。AWS 凭据先用 `boto3.Session().get_credentials()`，没有再用 `secrets.env`，都没有就询问并保存。钥匙：检测 agent（多个都有钥匙时询问一次，存为 `CNSR_SSH_AGENT`）→ 按别名找钥匙，没有就列出让你选，并建议新建同名钥匙 → `ensure_pub_file`。最后 `run_pipeline`，成功后输出节点行和 `client_lines`。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/qx.py src/cnsr/deploy/context.py src/cnsr/deploy/steps.py src/cnsr/commands tests/cnsr/test_qx.py tests/cnsr/test_add.py tests/cnsr/fakes.py
git commit -m "feat(add): orchestrate idempotent node deployment pipeline"
```

### Task 16: rm 命令

**Files:**
- Create: `src/cnsr/commands/rm.py`
- Test: `tests/cnsr/test_rm.py`

**Interfaces:**
- Consumes: Task 15 的 `Deps`、`Inventory`；Task 10 的 `Lightsail.delete`；Task 12 的 `delete_node_records`；Task 7 的 `config.remove_block`。
- Produces: `commands.rm.run(ns, deps: Deps | None = None) -> int`。

顺序：清单里没有这个别名就报错 `没有名为 <别名> 的节点`。列出将删除的内容，用 `confirm_text("输入别名确认删除", alias)` 确认。依次执行：AWS 删除实例和静态 IP → 删除 DNS 记录 → 删除 SSH 别名 → 删除清单条目（同时删掉配置行和节点 token）。前面任何一步有错误时，保留清单条目，列出没删干净的项，返回 1，以便重跑 `rm` 补删。全部成功返回 0。公钥文件和 agent 里的钥匙一律不动。

- [ ] **Step 1: 写失败的测试**

```python
def test_unknown_alias(fake_deps): ...            # returns 1, "没有名为 x 的节点"
def test_aws_full_removal(fake_deps): ...         # lightsail.delete("jp-1", "jp-1-ip") called; dns deleted; alias removed; inventory empty; returns 0
def test_vps_does_not_touch_lightsail(fake_deps): ...
def test_partial_failure_keeps_inventory(fake_deps):
    # dns delete returns ["删除 AAAA 记录失败"] -> returns 1; inventory still has node; output lists the failure
def test_confirmation_requires_exact_alias(fake_deps): ...   # inputs ["jp", "jp-1"] -> proceeds after second
```

- [ ] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/cnsr/test_rm.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现 `rm.py`**

AWS 的静态 IP 名约定为 `<别名>-ip`，实例名等于别名。这两个名字在 `step_ip` 里同样使用，并记录在 `Node.instance_name` 和 `Node.static_ip_name` 里，`rm` 以记录为准。

- [ ] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/cnsr -v`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/cnsr/commands/rm.py tests/cnsr/test_rm.py
git commit -m "feat(rm): remove node resources with retryable partial failures"
```

### Task 17: 真机验证（AWS 路径）

这一步要用你的 Cloudflare token、域名和 AWS 密钥，所以命令由你在自己的终端里运行，cnsr 询问时由你输入。执行者只负责准备、观察和记录，不替你输入任何凭据。小厂商路径等你安排好机器再测。

**Files:**
- Modify: `.notes/cnsr-redesign-spec_zh-cn.md` 第 15 节（把实测结果写进“已确认”和待实测表）

- [ ] **Step 1: 准备** — 确认 SSH agent 已解锁、里面有 `jp-key`；这台 Mac 上的圈X 处于可以暂停的状态。

- [ ] **Step 2: 部署** — 你运行：

```bash
uv run cnsr add cnsr-test-1 --aws jp
```

选钥匙时选 `jp-key`。期望：东京已有的 `jp-key` key pair 被按指纹复用，而不是重新导入。这一步同时验证了 Lightsail 的指纹格式。扫描前如果提示关闭代理，暂停圈X 后重跑同一条命令。

- [ ] **Step 3: 核对并记录** — 实例在 `ap-northeast-1`，规格 `nano_3_0`，系统为 Debian 13 或 12；防火墙只开 22/tcp、443/tcp、443/udp。`ssh cnsr-test-1` 走域名能登录。记录扫描耗时、命中数和通过筛选的候选数，以及控制端从外部测 v6 的结果（Worker 的 `connect()` 能否连 IPv6）。

- [ ] **Step 4: 客户端** — 把输出的两段配置粘贴进 iPhone 上的圈X，确认节点出现并能上网。

- [ ] **Step 5: 重跑** — 再运行一次 `uv run cnsr add cnsr-test-1`。期望：没有新实例，UUID 和 SNI 不变，圈X 里的节点仍然可用。

- [ ] **Step 6: 删除** — 你运行：

```bash
uv run cnsr rm cnsr-test-1
```

期望：实例和静态 IP 都已删除，两条 DNS 记录已删除，控制端返回的 snippet 里不再有这一行，`~/.ssh/config` 里没有了这个别名。即使前面的步骤失败，也必须完成这一步，确认没有留下计费资源。

- [ ] **Step 7: 写回设计文档** — 把 Step 3 的结果写进设计文档第 15 节。`.notes` 不纳入 git，不需要 commit。
