###### Windows 跨平台兼容性加固与健康体检优化提交总结

本文档沉淀本次会话针对 Windows 环境原生适配、SSH 参数解耦、Python 运行环境收敛与体检报告语义修正的完整开发记录。


**核心变更清单**

— 终端执行包装入口 — 新增 PowerShell 脚本 `cnsr.ps1` 与 CMD 批处理 `cnsr.cmd`，解决 Windows 终端直接执行 `.sh` 脚本报无法运行的系统限制。

— SSH 凭据代理与套接字隔离 — 在 `cnsr.sh` 中优先加载 Windows 原生 OpenSSH 路径以打通命名管道密钥代理；在所有 SSH/SCP 调用中针对 Windows 注入 `-o ControlMaster=no -o ControlPath=none`，规避套接字崩溃。

— Python 调用规范收敛 — 全面移除代码库中硬编码的 `python3` 调用，统一收敛为 `uv run python`，彻底适配 Windows 虚拟环境中缺乏 `python3.exe` 的缺陷。

— 文件编码与平台软锁降级 — 在 `lib/ssh.sh` 中将 Unix 独占的 `fcntl` 文件锁重构为安全宽容模式；在所有读写 `~/.ssh/config` 的 Python 片段中显式声明 UTF-8 编码，免疫 Windows 区域代码页 GBK 解码异常。

— 域名与 SNI 语义修正 — 规范体检脚本与 Telegram 报告模版，将直连 IP 场景与解析域名明确区分，纠正了历史版本中把直连 IP 标记为伪装域名的语义混淆问题。


**涉及模块与文件变动**

| 模块类别 | 变动文件 | 变更目标 |
| :--- | :--- | :--- |
| 入口适配 | `cnsr.ps1`, `cnsr.cmd`, `cnsr.sh` | 原生命令分发与 Windows OpenSSH 代理优先 |
| 核心管控 | `core/check.sh`, `core/init.sh`, `core/print.sh`, `core/rotate.sh`, `core/update.sh` | SSH 选项防污染、Python 命令统一与编码容错 |
| 云端与安全 | `core/init_aws.sh`, `core/destroy_aws.sh`, `lib/security.sh`, `lib/ssh.sh` | 规范 `uv run python` 调用与 `fcntl` 优雅降级 |
| 模版输出 | `templates/reality_check.template.sh`, `templates/tg_templates.sh`, `templates/tg_templates.md` | 区分节点连接域名与目标 SNI，IP 直连跳过 DNS |
