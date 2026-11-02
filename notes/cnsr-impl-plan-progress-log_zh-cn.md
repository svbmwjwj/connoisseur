# cnsr 进度显示与运行日志实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cnsr add` 和 `cnsr rm` 运行时屏幕只显示环节、整体进度和运行指示，每次运行自动写一个不含任何敏感值的日志文件，结束时打印日志路径。

**Architecture:** 日志用标准库 `logging`：新模块 `cnsr.runlog` 在一次运行期间给 `cnsr` logger 挂上文件 handler，并在写入前替换已登记的敏感值；各层（Ui、Remote、CloudflareClient、Lightsail）只管往 `cnsr.*` logger 写。屏幕用新模块 `cnsr.progress`：终端里是基于 rich 的 `LiveStages`，非终端是逐行输出的 `PlainStages`，两者接口相同；`Ui` 持有其中一个，所有提问都在它暂停时进行。

**Tech Stack:** Python 3.12、uv、rich（新增）、questionary（已有）、标准库 logging、pytest。

**Spec:** `.notes/cnsr-progress-log-design_zh-cn.md`（2026-10-18 定稿）。上位设计是 `cnsr-redesign-spec_zh-cn.md`。

## Global Constraints

- Python `>=3.12`。新增运行依赖只有 `rich>=13.7`，用 `uv add` 加入；不做全局安装。
- 命令和参数不变，`cli.HELP_TEXT` 一字不改；不加 `--verbose`、`--quiet` 或子命令。
- 屏幕文字和日志里的说明用简体中文；源码标识符、注释、commit 信息用英文。
- 日志目录：配置目录下的 `logs/`（`paths.config_dir(...) / "logs"`）。文件名 `<命令>-<别名>_<YYYYMMDD-HHMMSS>.log`；只保留最近 20 个；权限只给当前用户（Unix 600，Windows 用 `icacls`，与 `secrets.env` 相同）。
- 日志里绝不出现：Cloudflare API token、AWS access key ID 和 secret、客户端 token、管理 token、节点 token、Xray 私钥、Xray UUID、控制台密码、任何密码类输入。替换成 `***`。
- 成功的远程命令不记输出；上传的文件不记内容；云 API 不记请求体和响应体。
- 测试数据只用 `192.0.2.0/24`、`198.51.100.0/24`、`203.0.113.0/24`、`2001:db8::/32` 和 `example.com`。
- 单个文件不超过约 400 行；Python 模块 snake_case。
- 只提交本任务的文件（`git add <具体路径>`），不推送。单元测试不连接任何真实服务器或 API。
- 三个平台（macOS、Linux、Windows）都要能跑通；路径用 `pathlib`，Windows 上不能对打开着的文件改名。

## Review Focus

1. 提问时按 Ctrl-C — 进度显示不能停在暂停状态把终端弄乱，日志要写完结尾并标明中断。由 Task 4 的 `test_ctrl_c_in_a_question_resumes_the_display` 和 Task 1 的 `test_interrupted_run_still_writes_the_footer` 覆盖。
2. 敏感值作为普通回答输入（AWS access key ID 用的是 `ask`） — 日志里的回答必须是 `***`。由 Task 4 的 `test_answers_are_logged_but_secrets_are_not` 和 Task 5 的 `test_typed_aws_keys_stay_out_of_the_log` 覆盖。
3. 日志目录写不了（权限、磁盘满、`logs` 是个文件） — 命令照常运行，屏幕给一次警告，最后不打印日志路径。由 Task 1 的 `test_unwritable_logs_dir_does_not_stop_the_command` 和 Task 6 的 `test_no_log_line_when_the_log_cannot_be_written` 覆盖。
4. 终端很窄、标题很长 — 不报错，不把进度区折成乱行。由 Task 3 的 `test_live_fits_a_narrow_terminal` 覆盖。
5. 同一秒内运行两次 — 两个日志文件，互不覆盖。由 Task 1 的 `test_same_second_runs_get_distinct_files` 覆盖。

## 文件结构

| 路径 | 职责 |
| :--- | :--- |
| `src/cnsr/runlog.py`（新） | 一次运行的日志文件：命名、权限、开头和结尾、敏感值替换、保留 20 个 |
| `src/cnsr/progress.py`（新） | 屏幕上的环节显示：`PlainStages`、`LiveStages`、`terminal_display()` |
| `src/cnsr/ui.py` | 持有显示对象；所有输出同时写日志；提问时暂停显示 |
| `src/cnsr/cli.py` | 为 `add`、`rm` 开启和结束运行日志，最后一行打印日志路径 |
| `src/cnsr/ssh/remote.py`、`cloudflare/api.py`、`aws/lightsail.py` | 每次远程命令和 API 调用写一行日志 |
| `src/cnsr/localconf.py`、`state.py`、`deploy/steps_node.py`、`server/harden.py` | 在敏感值出现的地方登记它 |
| `src/cnsr/deploy/steps.py`、`steps_*.py`、`commands/add.py`、`commands/rm.py`、`scan/probe.py` | 报告环节和扫描进度；过程信息改为只写日志 |
| `tests/cnsr/display_fakes.py`（新） | 记录调用的假显示对象，供 Task 4、5 的测试使用 |

### Task 1: 运行日志模块

**Files:**
- Create: `src/cnsr/runlog.py`
- Modify: `src/cnsr/localconf.py`（把 `_restrict_windows` 改成公开的 `restrict_to_user`，`save` 改用它）
- Test: `tests/cnsr/test_runlog.py`

**Interfaces:**
- Produces:
  - `LOGGER_NAME = "cnsr"`、`KEEP_LOGS = 20`、`LOGS_DIR_NAME = "logs"`
  - `log_name(command: str, alias: str | None, started: datetime) -> str`
  - `secret(value: str | None) -> None`：登记到当前运行；没有运行或值短于 6 个字符时什么都不做。
  - `current() -> Run | None`、`alias_known(alias: str) -> None`（当前运行开始时没有别名才改名）
  - `class Run`：属性 `path: Path | None`（写不了日志时为 None）、`exit_code: int | None`；方法 `rename_for(alias: str) -> None`。
  - `started(logs_dir: Path, command: str, alias: str | None, argv: list[str], *, now: Callable[[], datetime] = datetime.now, restrict: Callable[[Path], None] | None = None) -> ContextManager[Run]`：`restrict` 默认是 `localconf.restrict_to_user`。
  - `localconf.restrict_to_user(path: Path, *, platform: str = sys.platform, run=subprocess.run) -> None`：Unix 上 `chmod 600`，Windows 上沿用现在的 `icacls` 调用。

- [ ] **Step 1: 写失败的测试** — `tests/cnsr/test_runlog.py`：
  - `test_log_name`：`log_name("add", "cnsr-test-1", datetime(2026, 10, 18, 15, 30, 12)) == "add-cnsr-test-1_20261018-153012.log"`；别名为 None 时是 `"add_20261018-153012.log"`。
  - `test_lines_carry_time_and_level`：在 `started` 里 `logging.getLogger("cnsr.x").info("你好")`，文件里有一行匹配 `r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} INFO +你好$"`。
  - `test_header_and_footer`：文件开头含 cnsr 版本、`argv`、Python 版本；`run.exit_code = 1` 后退出，结尾一行含 `退出码 1` 和总耗时。
  - `test_registered_secrets_never_reach_the_file`：`secret("tok-1234567890")` 后写 `"a tok-1234567890 b"`，文件里是 `"a *** b"`；`secret("jp")` 不生效，`"jp"` 原样保留。
  - `test_secret_without_a_run_is_ignored`：不在运行中调用 `secret("x" * 10)` 不报错。
  - `test_file_is_private`：非 Windows 上文件权限是 `0o600`；`restrict` 被调用且参数是日志路径。
  - `test_only_the_newest_20_are_kept`：目录里先放 25 个旧 `.log`（递增的 mtime）和一个 `notes.txt`，运行结束后剩 20 个 `.log`（含本次），`notes.txt` 还在，删的是最旧的。
  - `test_same_second_runs_get_distinct_files`：两次 `started` 用同一个 `now`，得到两个不同的文件且都存在。
  - `test_alias_known_renames_the_file`：别名为 None 开始，`alias_known("jp-1")` 后 `run.path.name` 以 `add-jp-1_` 开头，旧文件不存在，之后的日志写进新文件。
  - `test_unwritable_logs_dir_does_not_stop_the_command`：`logs_dir` 是一个已存在的普通文件，`started` 不抛异常，`run.path is None`，期间写日志不报错。
  - `test_logger_is_released_after_the_run`：退出后 `current() is None`，`cnsr` logger 上没有本次的 handler，`propagate` 恢复为 True（单元测试里 `caplog` 依赖它）。
  - `test_interrupted_run_still_writes_the_footer`：在 `started` 里抛 `KeyboardInterrupt`，异常照常抛出，文件结尾一行含 `已中断`。

- [ ] **Step 2: 运行测试确认失败** — `uv run pytest tests/cnsr/test_runlog.py -q`，期望：`ModuleNotFoundError: cnsr.runlog`。

- [ ] **Step 3: 实现 `src/cnsr/runlog.py` 和 `localconf.restrict_to_user`** — 文件先用 `os.open(..., O_CREAT | O_EXCL | O_WRONLY, 0o600)` 独占创建（重名时在秒后加 `-2`、`-3`），再交给 `logging.FileHandler(mode="a", encoding="utf-8")`；替换敏感值放在 handler 的 `Filter` 里，作用于 `record.getMessage()` 的结果，长的值先替换。运行期间 `cnsr` logger 级别 INFO、`propagate = False`，结束时都恢复。改名时先关闭 handler 的流、改名、再重新打开（Windows 不能改名打开着的文件）。

- [ ] **Step 4: 运行测试确认通过** — `uv run pytest tests/cnsr/test_runlog.py tests/cnsr/test_localconf.py -q`，期望全部通过。

- [ ] **Step 5: Commit** — `git add src/cnsr/runlog.py src/cnsr/localconf.py tests/cnsr/test_runlog.py`，信息如 `feat(runlog): write each add or rm run to a private log file with secrets masked`。

### Task 2: 远程命令、云 API 和敏感值接入日志

**Files:**
- Modify: `src/cnsr/ssh/remote.py`、`src/cnsr/cloudflare/api.py`、`src/cnsr/aws/lightsail.py`、`src/cnsr/localconf.py`、`src/cnsr/state.py`、`src/cnsr/deploy/steps_node.py`、`src/cnsr/server/harden.py`
- Test: `tests/cnsr/test_ssh_remote.py`、`tests/cnsr/test_cloudflare.py`、`tests/cnsr/test_lightsail_client.py`、`tests/cnsr/test_localconf.py`、`tests/cnsr/test_state.py`

**Interfaces:**
- Consumes: `runlog.secret(value)`；各模块用 `logging.getLogger(__name__)`（都在 `cnsr.*` 之下）。
- Produces: 无新接口。登记点固定为：`localconf.load` 读到的 `CLOUDFLARE_API_TOKEN`、`AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY`；`ControlMeta.__post_init__` 的两个 token；`Node.__post_init__` 的 `node_token`（有值时）；`XrayInfo.__post_init__` 的 `uuid`；`steps_node` 生成 `node_token` 处；`steps_node._identity` 拿到私钥处（新生成和从节点读回两条路径）；`harden._stage` 生成控制台密码处（在显示之前）。

- [ ] **Step 1: 写失败的测试**（用 `caplog` 抓 `cnsr` logger；登记用 `monkeypatch` 替换 `runlog.secret` 收集值）：
  - `test_run_is_logged_without_output_on_success`：`Remote.run(["echo", "hi"])` 成功、stdout 是 `"out-1234567"`，日志里有目标地址、`echo hi`、退出码 0，没有 `out-1234567`。
  - `test_failed_run_logs_both_tails`：退出码 23、stdout 含 `Failed to get format`、stderr 含 `boom`，日志里两者都有。
  - `test_input_and_uploaded_content_are_never_logged`：`run(["chpasswd"], input="admin:pw-9876543")` 和 `put_text(path, "content-7654321", "600")` 之后，日志里没有这两个值，`put_text` 那行有路径和 `600`。
  - `test_cloudflare_requests_are_logged_without_bodies`：一次 `PUT` 带 json `{"value": "body-7654321"}`，日志有方法、路径、状态码，没有 `body-7654321` 和 token。
  - `test_lightsail_calls_are_logged_with_the_error_code`：一次成功、一次 `NotFoundException`，日志各一行，含操作名和错误码。
  - `test_load_registers_the_credentials`：`localconf.load` 登记三个凭据值，不登记 `CLOUDFLARE_ZONE`。
  - `test_tokens_and_uuid_are_registered`：构造 `ControlMeta`、`Node.from_json`（带 `node_token` 和 `xray`）时登记两个 token、节点 token 和 UUID。

- [ ] **Step 2: 运行测试确认失败** — `uv run pytest tests/cnsr/test_ssh_remote.py tests/cnsr/test_cloudflare.py tests/cnsr/test_lightsail_client.py tests/cnsr/test_localconf.py tests/cnsr/test_state.py -q`，期望：新测试失败。

- [ ] **Step 3: 实现** — `Remote.run` 在返回或抛错前写一行（`run_script` 记脚本名和参数，不记脚本正文）；失败时再写 stdout、stderr 各自最后若干行（行数由实现者定）。`CloudflareClient.request` 和 `Lightsail._call` 各写一行。按上面的登记点调用 `runlog.secret`。

- [ ] **Step 4: 运行全部测试** — `uv run pytest -q`，期望全部通过。

- [ ] **Step 5: Commit** — 只加上面列出的文件，信息如 `feat(log): log remote commands and API calls, and register secrets where they appear`。

### Task 3: 进度显示模块

**Files:**
- Create: `src/cnsr/progress.py`
- Modify: `pyproject.toml`、`uv.lock`（`uv add "rich>=13.7"`）
- Test: `tests/cnsr/test_progress.py`

**Interfaces:**
- Produces:
  - `Outcome = Literal["done", "failed", "interrupted"]`
  - `class StageDisplay(Protocol)`：`busy(text: str) -> None`、`idle() -> None`、`begin(heading: str, titles: list[str]) -> None`、`start(number: int) -> None`（从 1 开始，同时结束上一个环节）、`count(done: int, total: int) -> None`、`end(outcome: Outcome) -> None`、`line(text: str) -> None`、`paused() -> ContextManager[None]`、`transient(text: str) -> ContextManager[None]`。
  - `class PlainStages(StageDisplay)`：`__init__(self, out: TextIO, *, clock: Callable[[], float] = time.monotonic)`。
  - `class LiveStages(StageDisplay)`：`__init__(self, console: rich.console.Console, *, auto_refresh: bool = True, clock: Callable[[], float] = time.monotonic)`。
  - `terminal_display(stdout: TextIO | None = None) -> StageDisplay`：stdout 是终端时返回 `LiveStages(Console())`，否则 `PlainStages(stdout)`。
  - `elapsed(seconds: float) -> str`：`"0:07"`、`"2:37"`、`"1:02:03"`。

- [ ] **Step 1: 写失败的测试** — `tests/cnsr/test_progress.py`（时钟用可控的假函数；`LiveStages` 用 `Console(file=StringIO(), force_terminal=True, width=80, color_system=None)` 和 `auto_refresh=False`）：
  - `test_elapsed`：上面三个例子。
  - `test_plain_stages_print_one_line_per_start_and_end`：`begin("cnsr add jp-1 · AWS 东京", ["甲", "乙", "丙"])`、`start(1)`、5 秒后 `start(2)`、1 秒后 `end("failed")`，输出恰好是 `"cnsr add jp-1 · AWS 东京\n[1/3] 甲\n[1/3] 甲：完成（0:05）\n[2/3] 乙\n[2/3] 乙：失败（0:01）\n"`；`"interrupted"` 时是 `：已中断（…）`，`"done"` 是 `：完成（…）`。
  - `test_plain_busy_line_count_and_transient`：`busy("检查控制端")` 输出 `"检查控制端……\n"`；`count`、`paused`、`idle` 不输出；`transient("密码 X")` 输出一次 `"密码 X\n"`。
  - `test_live_end_leaves_the_final_block`：三个环节都完成后 `end("done")`，输出里有 `✓ 甲`、`✓ 乙`、`✓ 丙` 和 `3/3`。
  - `test_live_marks_a_failed_or_interrupted_stage`：`end("failed")` 时有 `✗ 乙`；`end("interrupted")` 时有 `已中断`。
  - `test_live_count_shows_the_numbers`：`start(1)`、`count(1534, 3071)` 后刷新一次，输出里有 `1534 / 3071`。
  - `test_live_pause_leaves_one_context_line_per_stage`：`start(2)` 后进入两次 `paused()`，输出里作为普通行的 `[2/3] 乙` 恰好出现一次。
  - `test_live_transient_uses_the_alternate_screen`：`transient("密码 X")` 里的文字只出现在 `\x1b[?1049h` 和 `\x1b[?1049l` 之间。
  - `test_live_fits_a_narrow_terminal`：`width=30`、标题 40 个汉字，渲染不报错，每行显示宽度不超过 30。
  - `test_terminal_display_picks_by_tty`：假的 stdout 的 `isatty()` 为真得到 `LiveStages`，为假得到 `PlainStages`。

- [ ] **Step 2: 运行测试确认失败** — `uv run pytest tests/cnsr/test_progress.py -q`，期望：`ModuleNotFoundError: cnsr.progress`。

- [ ] **Step 3: 实现 `src/cnsr/progress.py`** — `LiveStages` 用 `rich.live.Live(transient=True)` 画进度区，`end` 时把最终状态用 `console.print` 留在屏幕上；`paused` 先停住 Live，当前环节第一次暂停时打印一行 `[n/N] 标题`，`finally` 里恢复；`transient` 用 `console.screen()`（终端的备用屏幕），离开时文字随之消失；`line` 在 Live 运行时用 `console.print`，打印在进度区上方。画面样式见设计文档“屏幕：运行中”，转动符号和颜色由实现者定。

- [ ] **Step 4: 运行测试确认通过** — `uv run pytest tests/cnsr/test_progress.py -q`，期望全部通过。

- [ ] **Step 5: Commit** — `git add pyproject.toml uv.lock src/cnsr/progress.py tests/cnsr/test_progress.py`，信息如 `feat(progress): stage list, overall bar and spinner, plain lines without a terminal`。

### Task 4: Ui 接入显示和日志

**Files:**
- Modify: `src/cnsr/ui.py`、`tests/cnsr/test_ui.py`
- Create: `tests/cnsr/display_fakes.py`

**Interfaces:**
- Consumes: Task 3 的 `StageDisplay`、`PlainStages`、`Outcome`；Task 1 的 `runlog.secret`。
- Produces:
  - `Ui.__init__` 新增参数 `display: StageDisplay | None = None`，默认 `PlainStages(out)`。
  - 新方法：`begin(heading: str, titles: list[str])`、`stage(number: int)`、`stage_count(done: int, total: int)`、`end(outcome: Outcome)`、`busy(text: str)`、`idle()`、`detail(msg: str)`（只写日志）、`handover() -> ContextManager[None]`（暂停显示，把终端交给子进程）、`transient(text: str) -> ContextManager[None]`。
  - `ask` 新增参数 `sensitive: bool = False`。删除 `step()`。
  - 日志：写到 `logging.getLogger("cnsr.ui")`。`info`、`detail` 是 INFO，`warn` 是 WARNING，`error` 是 ERROR；每个问题写 `问：<提示>` 和 `答：<回答>`（`choose` 记选中的那一项的文字；`secret` 和 `sensitive` 的回答记 `***` 并调用 `runlog.secret`）；`begin`、`stage`、`end` 各写一行。
  - `tests/cnsr/display_fakes.py`：`class RecordingDisplay`，实现 `StageDisplay`，把每次调用按顺序记进 `calls: list[tuple]`，并有属性 `paused_now: bool`。

- [ ] **Step 1: 写失败的测试** — `tests/cnsr/test_ui.py`：
  - `test_detail_goes_only_to_the_log`：`detail("安装 Docker")` 后屏幕为空，`caplog` 里有。
  - `test_info_and_warn_go_to_screen_and_log`：`info` 和 `warn` 屏幕和日志都有，`warn` 的级别是 WARNING。
  - `test_questions_pause_the_display`：用 `RecordingDisplay`，`ask`、`secret`、`choose`、`confirm_text` 读输入时 `paused_now` 为真，返回后为假。
  - `test_ctrl_c_in_a_question_resumes_the_display`：`select_fn` 抛 `KeyboardInterrupt`，异常照常抛出，`paused_now` 为假。
  - `test_answers_are_logged_but_secrets_are_not`：`ask` 的回答 `jp-1` 记成 `答：jp-1`；`secret` 和 `ask(..., sensitive=True)` 的回答不出现在日志里、出现 `答：***`，并都传给了 `runlog.secret`。
  - `test_stages_without_a_display_print_plain_lines`：`Ui(out=StringIO())` 上 `begin("h", ["甲", "乙"])`、`stage(1)`，输出含 `[1/2] 甲`。
  - 删除 `test_step_format`。

- [ ] **Step 2: 运行测试确认失败** — `uv run pytest tests/cnsr/test_ui.py -q`，期望：新测试失败。

- [ ] **Step 3: 实现** — 改 `ui.py`。提问都包在 `self._display.paused()` 里，用 `finally` 保证恢复；`error` 也在暂停时打印到 stderr。此时其他模块里对 `ui.step` 的调用（只有 `deploy/steps.py`）改成 `begin` 和 `stage`，标题行先用 `f"cnsr add {alias}"`，Task 5 再补来源。

- [ ] **Step 4: 运行全部测试** — `uv run pytest -q`，期望全部通过（部署测试里断言 `[1/7] 确定服务器地址` 的仍然成立）。

- [ ] **Step 5: Commit** — `git add src/cnsr/ui.py src/cnsr/deploy/steps.py tests/cnsr/test_ui.py tests/cnsr/display_fakes.py`，信息如 `feat(ui): drive the stage display, pause it for questions and log everything`。

### Task 5: add、rm、清理、扫描和加固接入

**Files:**
- Modify: `src/cnsr/deploy/steps.py`、`steps_host.py`、`steps_sni.py`、`steps_node.py`、`src/cnsr/deploy/context.py`、`src/cnsr/scan/probe.py`、`src/cnsr/server/harden.py`、`src/cnsr/commands/add.py`、`src/cnsr/commands/add_keys.py`、`src/cnsr/commands/rm.py`、`src/cnsr/cloudflare/dns.py`（如需记录公共 DNS 结果）
- Modify: `tests/cnsr/deploy_fakes.py`、`tests/cnsr/conftest.py`
- Test: 新建 `tests/cnsr/test_add_screen.py`、`tests/cnsr/test_rm_screen.py`

**Interfaces:**
- Consumes: Task 4 的 `Ui` 新方法；Task 1 的 `runlog.alias_known`、`runlog.secret`；Task 4 的 `RecordingDisplay`。
- Produces:
  - `deploy.steps.heading(req: AddRequest) -> str`：AWS 是 `f"cnsr add {alias} · AWS {REGION_NAMES[region]}"`，`REGION_NAMES = {"jp": "东京", "sg": "新加坡", "us": "俄勒冈"}`；已有服务器是 `f"cnsr add {alias} · 已有服务器 {ip}"`。
  - `run_pipeline(ctx)`：开始时 `ui.begin(heading(ctx.req), list(TITLES.values()))`，每步 `ui.stage(n)`；全部成功 `ui.end("done")`；`CnsrError` 时 `ui.end("failed")`、`KeyboardInterrupt` 时 `ui.end("interrupted")`，再照旧保存进度并抛出。
  - `probe.scan(ips: list[str], *, progress: Callable[[int, int], None] | None = None, port=443, concurrency=64, timeout=5.0) -> list[Hit]`：每探完一个地址调用一次 `progress(已完成数, 总数)`。`Deps.scan` 的类型改为 `Callable[..., list[Hit]]`，`step_scan` 传 `progress=ui.stage_count`。
  - `rm.RM_TITLES = {"aws": "删除 AWS 实例和静态 IP", "dns": "删除 DNS 记录", "alias": "删除 SSH 别名", "record": "删除控制端登记"}`；`rm.rm_stages(node: Node) -> list[str]`（小厂商节点没有 `"aws"`）；`remove_node(..., *, on_stage: Callable[[str], None] | None = None) -> list[str]` 在每部分开始前调用 `on_stage(键)`。
  - `deploy_fakes.Terminal`：新增 `screen`（stdout 加 stderr）和 `log`（测试期间挂在 `cnsr` logger 上的 handler 收到的文字）；`text` 改为 `screen + log`，现有测试的文字断言因此照常成立。`FakeServer` 记录 `chpasswd` 的输入，供 Task 6 使用。

- [ ] **Step 1: 写失败的测试**：
  - `test_add_screen.py::test_a_deployment_shows_stages_not_details`：一次 AWS 部署后，`terminal.screen` 含 `cnsr add jp-1 · AWS 东京`、`[1/7] 确定服务器地址` 和 `[7/7] 登记节点并切换 SSH 别名：完成`，不含 `安装 Docker`、`节点验证了`；`terminal.log` 含 `节点验证了`。
  - `test_the_scan_reports_its_count`：用 `RecordingDisplay`，最后一次 `count` 是 `(3071, 3071)`。
  - `test_the_root_password_login_hands_the_terminal_over`：小厂商服务器、公钥还没装，调用 `install_key` 时 `paused_now` 为真。
  - `test_the_console_password_is_shown_transiently_and_kept_out_of_the_log`：小厂商部署，`transient` 收到的文字含控制台密码，`terminal.log` 不含它。
  - `test_a_failed_step_ends_the_display_as_failed`：`verify-reality.sh` 失败，显示收到 `end("failed")`；`KeyboardInterrupt` 时收到 `end("interrupted")`。
  - `test_cleanup_is_one_busy_line_and_the_result`：第一次 AWS 部署失败后，屏幕上清理部分只有 `busy` 的一行和 `已清理干净` 那一行，`删除 AWS 上的静态 IP 和实例` 只在日志里。
  - `test_typed_aws_keys_stay_out_of_the_log`：`aws_chain = False`，输入 access key ID 和 secret，日志里两者都没有。
  - `test_rm_screen.py::test_rm_shows_its_stages`：AWS 节点 `rm` 后屏幕有 `[1/4] 删除 AWS 实例和静态 IP` 到 `[4/4] 删除控制端登记：完成`；小厂商节点是 3 个环节。

- [ ] **Step 2: 运行测试确认失败** — `uv run pytest tests/cnsr/test_add_screen.py tests/cnsr/test_rm_screen.py -q`，期望：新测试失败。

- [ ] **Step 3: 实现** — 按上面的接口接线，并按下面的规则把现有的 `ui.info` 逐个改为 `ui.detail` 或保留：
  - 保留上屏 — 问题前你必须读到的说明（第一次运行的 Cloudflare 说明、AWS 凭据说明、钥匙建议、装入公钥前关于 root 密码的说明、`rm` 的删除清单）、结束时的总结和圈X 配置、清理的最终结果、`rm` 没删干净时的清单。
  - 改为只写日志 — 其余过程信息，包括加固的进度、Docker、扫描统计、候选和选定的 SNI、外部探测、直连检查的地址、公共 DNS 结果、`remove_node` 里的各行。
  - 准备阶段 — `prepare` 里检查控制端前调用 `ui.busy("检查 Cloudflare 控制端")`；问到别名后调用 `runlog.alias_known(alias)`；输入 AWS access key ID 用 `ask(..., sensitive=True)`。
  - 加固 — 控制台密码先 `runlog.secret(password)`，再 `with ui.transient(说明文字): ui.confirm_text(...)`。
  - 登录 — `deps.install_key(...)` 包在 `with deps.ui.handover():` 里。
  - 清理 — `_clean_up` 用 `ui.busy(...)` 代替开头那行，最后 `ui.idle()` 再 `ui.info` 结果。
  - `rm` — 确认之后 `ui.begin(f"cnsr rm {alias}", [RM_TITLES[k] for k in rm_stages(node)])`，`on_stage` 映射到 `ui.stage(序号)`，结束时 `end("done")` 或 `end("failed")`。

- [ ] **Step 4: 运行全部测试** — `uv run pytest -q`，期望全部通过。

- [ ] **Step 5: Commit** — 只加上面列出的文件，信息如 `feat(add, rm): show stages and scan progress, keep process details in the log`。

### Task 6: 命令行接入日志，端到端检查

**Files:**
- Modify: `src/cnsr/cli.py`、`src/cnsr/deploy/context.py`
- Test: `tests/cnsr/test_cli.py`、新建 `tests/cnsr/test_run_log_e2e.py`

**Interfaces:**
- Consumes: Task 1 的 `runlog.started`、`LOGS_DIR_NAME`；Task 3 的 `terminal_display()`。
- Produces: `default_deps()` 里 `ui=Ui(select_fn=terminal_select(), display=terminal_display())`。`main` 对 `add`、`rm` 在 `runlog.started(paths.config_dir(...) / LOGS_DIR_NAME, ns.command, ns.alias, argv)` 里执行，退出码写进 `run.exit_code`；最后一行用 stdout 打印 `日志：<run.path>`（成功、失败、`CnsrError`、Ctrl-C 都打印；`run.path` 为 None 时打印一次 `警告：无法写日志：<原因>`，不打印路径行）。

- [ ] **Step 1: 写失败的测试**：
  - `test_cli.py::test_the_log_path_is_the_last_line`：`XDG_CONFIG_HOME` 指向临时目录，`monkeypatch` 让 `add.run` 分别返回 0、抛 `CnsrError`、抛 `KeyboardInterrupt`，三种情况 stdout 最后一行都以 `日志：` 开头，文件存在，`KeyboardInterrupt` 时退出码是 130。
  - `test_help_and_usage_errors_write_no_log`：`cnsr -h`、`cnsr`、`cnsr nope` 之后 `logs/` 不存在。
  - `test_no_log_line_when_the_log_cannot_be_written`：`logs` 是一个文件，命令照常运行，有一行警告，没有 `日志：`。
  - `test_run_log_e2e.py::test_a_full_run_log_holds_no_secret`：在 `runlog.started(tmp)` 里依次跑一次 AWS 部署、一次需要加固的小厂商部署和一次 `rm`；收集所有敏感值（假 Cloudflare token `t-secret`、KV 里的客户端和管理 token、各节点的 node token 和 UUID、`server.generated` 里的私钥、`chpasswd` 输入里的控制台密码）。断言日志里一个都没有，并且日志里有环节行（`[4/7] 扫描候选 SNI`）和远程命令行（含 `docker`）。

- [ ] **Step 2: 运行测试确认失败** — `uv run pytest tests/cnsr/test_cli.py tests/cnsr/test_run_log_e2e.py -q`，期望：新测试失败。

- [ ] **Step 3: 实现** — 改 `cli.main` 和 `default_deps`。

- [ ] **Step 4: 运行全部测试和 Worker 测试** — `uv run pytest -q` 和 `uv run node --test tests/worker/*.test.mjs`，期望全部通过；再在终端里手动跑 `uv run cnsr add` 并在第一个问题处按 Ctrl-C，看到进度区正常收起、最后一行是日志路径，日志文件里有 `已中断`。

- [ ] **Step 5: Commit** — `git add src/cnsr/cli.py src/cnsr/deploy/context.py tests/cnsr/test_cli.py tests/cnsr/test_run_log_e2e.py`，信息如 `feat(cli): log every add and rm run and print where the log is`。
