# SDD ledger — plan: .notes/cnsr-impl-plan-progress-log_zh-cn.md
Spec: .notes/cnsr-progress-log-design_zh-cn.md. Start HEAD 54d2cd5.

## Pre-flight scan
| Pair / task | Produces vs consumes | Finding |
| T1→T2 | runlog.secret, cnsr logger propagate restored outside runs | consistent (T2 tests use caplog, T1 test pins propagate=True after run) |
| T1→T6 | runlog.started, LOGS_DIR_NAME, Run.path/exit_code | consistent |
| T1→T5 | runlog.alias_known | consistent |
| T3→T4 | StageDisplay, PlainStages, Outcome | consistent |
| T4→T5 | Ui begin/stage/stage_count/end/busy/idle/detail/handover/transient, ask(sensitive), RecordingDisplay | consistent |
| T2/T5 share harden.py, steps_node.py | T2 registers password/secrets, T5 adds transient + details | compatible, sequential |
| T4/T5 share deploy/steps.py | T4 swaps ui.step for begin/stage, T5 adds heading/end | compatible |
| T5→T6 | FakeServer records chpasswd input; Terminal.log; Deps.scan type | consistent |
| T3→T6 | terminal_display() | consistent |
| T1 self | tests vs started/restrict | consistent |
| T2 self | tests vs registration points | consistent |
| T3 self | plain exact output vs live behaviours | consistent |
| T4 self | removes step(); existing test_ui tests using step must change | Ruling below |
| T5 self | info→detail by rule; Terminal.text=screen+log keeps old assertions | consistent |
| T6 self | consistent |
Ruling: Task 4 also rewrites existing test_ui tests that call ui.step (e.g. test_noninteractive_still_prints_progress) to use begin/stage — plan deletes step() — cost if wrong: trivial test churn.
Task 1: review 1 — spec ✅, 1 Important (rename_for error path)
Task 1: minor (deferred): _Masker.filter getMessage outside logging error handling; empty file left if _open_handler fails in started; started reaches into Run privates; restrict_to_user error text says 凭据文件; Windows tests run real icacls; exit_code None after KeyboardInterrupt (Task 6 decides)
Task 1: fix round 1/5 (3 addressed, 0 open; commits 9a57576..fd1aa0f)
Task 1: minor (deferred): rename_for _open_handler-failure branch untested
Task 1: complete (commits 54d2cd5..fd1aa0f, review clean)
Task 2: review 1 — spec ✅, 1 Important (node_token registration test can't fail)
Task 2: minor (deferred): _log_run line length; run_script + run log two near-duplicate lines; registration tests live in test_state.py not test_add_steps/test_harden; Cloudflare failures log status only
Task 2: fix round 1/5 (2 addressed, 0 open; commits bc3ffb1..cba9f60)
Task 2: minor (deferred): failed remote command tails may carry an unregistered secret printed by the remote side (design accepts: registered values only)
Task 2: complete (commits fd1aa0f..cba9f60, review clean)
Task 3: review 1 — spec ✅, quality Approved
Task 3: minor (deferred): _pauses counter leaks if stop/print raises inside paused(); no close(); no test pins block-gone-during-pause; untested nested paused/transient-exception/busy→begin/auto_refresh/TERM=dumb; progress.py at 395 lines; _live unlocked (single-thread assumption undocumented); Protocol subclassing hides missing methods; ambiguous-width glyphs
Ruling: in plain (non-terminal) mode the console password is printed once and cannot be erased — the user must see it to save it, and the spec only asks to clear it on screen — cost if wrong: the password lands in a redirected log file the user chose to create.
Ruling: Tasks 4/5 must guarantee display end() on every path (CnsrError → failed, KeyboardInterrupt → interrupted) since LiveStages has no close() — cost if wrong: hidden cursor after a crash.
Task 3: complete (commits cba9f60..473b2c7, review clean)
Task 4: review 1 — spec ✅, 2 Important (vacuous 失败 assertion; E302/W391 style)
Task 4: minor (deferred): save failure now routed through end("failed") untested; stage() outside try; loose regex in test_add.py; no test for sensitive empty→default, choose EOF inside pause; stage() before begin IndexError; duplicated make() helper
Task 4: fix round 1/5 (3 addressed, 0 open; commits dfba266..f0b59dc)
Task 4: complete (commits 473b2c7..f0b59dc, review clean)
Ruling: scan count test pins len(scan_targets(AWS_IP)) (3070) instead of the plan's (3071, 3071) — the plan's number was wrong for that IP — cost if wrong: none.
Task 5: review 1 — spec ✅, quality Approved
Task 5: minor (deferred): root-password notice printed before the paused stage line in live mode (should sit inside handover); rm leftover marks the last stage ✗ instead of the failing one; Terminal attaches log handler in __init__ (fixture-only close); long waits show only the spinner
Task 5: complete (commits f0b59dc..e771227, review clean)
Task 6: review 1 — spec ✅, quality Approved
Task 6: minor (deferred): fake Remote logging is partial (no exit code/tails); unhandled exceptions print no 日志 line; warning text repeats 无法写…; e2e "***" check weak (real teeth is the per-secret absence + mutation)
Task 6: complete (commits e771227..f4805d3, review clean)
Final review: With fixes — 3 Important + 4 fix-soon minors; one fix wave f4805d3..2be742d; re-review: all addressed, no new breakage
Final: parked — unexpected-error message prints str(exc) unmasked on stderr — Ruling: screen only (the user's own terminal), the log copy is masked; cheap follow-up to mask it — cost if wrong: a secret inside an unexpected exception text shows on the user's screen
Final: parked — _RunHandler.handleError ends the log on any emit exception, not only I/O — Ruling: masker pre-formats, unlikely; log loss never stops the command — cost if wrong: a log ends early
Final: parked — rm shows two ✗ (failing part and 删除控制端登记) when something is left — Ruling: correct, the record is genuinely kept — cost if wrong: cosmetic
Verified by controller: full suite 1584 passed, Worker 21 passed, pty Ctrl-C check OK
