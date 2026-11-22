"""Pipeline step 4: Docker Engine and its compose plugin, for the Xray node or the user's own services."""

from __future__ import annotations

from cnsr.deploy.context import DeployContext


def step_docker(ctx: DeployContext) -> None:
    """Install Docker from its official repository; a server where it already works is left alone."""
    ctx.deps.ui.detail("安装 Docker（已装好就跳过）。")
    ctx.remote().run_script("install-docker.sh", [])
