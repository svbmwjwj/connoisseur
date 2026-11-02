###### cnsr 可靠性诊断 — SNI 自愈与部署加固

2026-10-16 针对两个用户反馈做的代码审计：SNI 失效防不住、自动轮换效果差；批量部署、单台部署和加固逻辑有问题。审计全程只读，没有连接任何服务器，结论来自代码追踪、本地离线复现和 `logs/` 里的历史部署日志。

**方法**

| 环节 | 做法 | 规模 |
| :--- | :--- | :--- |
| 多视角审计 | 8 个审计代理各负责一个视角：失效检测、选优、自愈存活、扫描链路、单台部署、批量部署、加固、跨模块契约 | 109 条 |
| 反驳式复核 | 每个视角由一名独立反驳者逐条复核，多数附带离线复现 | 驳回 3 条 |
| 完整性补查 | 评审代理找出 3 个没人审过的区域，补审后再复核 | 新增 23 条 |
| 异构交叉 | Codex 在只读沙箱里独立盲审，其中 7 条只有它报告，由 2 名反驳者复核 | 见“Codex 独有结论” |

最终保留 129 条，其中 critical 14、high 21、medium 49、low 45，但多个视角报告了同一问题，去重后约 90 个独立问题。每条的完整机制、证据和复核意见见附录 `reliability-audit-findings_20261016_zh-cn.md`。

**一句话结论**

SNI 自愈分三层出问题：它看不到真正的失效，修复动作不对症，修完还会让所有客户端断线。更底层的是，多数部署路径上自愈循环根本没在运行。部署和加固方面，单台 `init` 每次都失败，`--detach` 实际什么都不部署，Lightsail 上的 `--harden` 一定会把主机锁死。

**根因一：自愈看不到真正的失效（设计层）**

— DET-1 / SEL-1 — 所有健康探测都从 VPS 自己发出：本机回环握手、向境内 DNS 查投毒、从 VPS 直连 dest。没有任何信号来自境内到节点 `IP:443` 的路径，而 GFW 封 IP、封端口或针对 IP+SNI 组合的阻断，在服务器视角下全都显示为“健康”。
— DET-1 / GAP3-10 — 即便检测到问题，自愈唯一的动作是换 SNI。封 IP 才是最常见的失效，但 `rotate-ip` 只能手动执行，仓库里没有任何自动触发路径。
— RUN-5 — 每次自动轮换都会同时重置 UUID、私钥和 shortId 并重启 Xray，新凭据只靠一条 Telegram 消息送达，所以所有客户端都要手动重新导入。服务端宣称“已恢复”时，客户端恰恰全部断线。
— RUN-7 / BATCH-5 — `init-aws`（包括单台）设置了 `BATCH_MODE`，节点自己的推送被静音，而本地汇总又在节点生成配置之前就去取 `vless.txt`，所以初始订阅基本送不到。
— GAP2-1 — AAAA 记录总会发布，链接里用的也是域名，但自愈和体检只测 IPv4 或回环，IPv6 入站坏了系统完全不知道。

**根因二：自愈循环在多数节点上没有运行（实现层）**

— INIT-2 — `init` 的远端脚本在 `set -e` 下第二次安装 crontab。`crontab -l | grep -v runner.sh` 过滤后输出为空，grep 返回 1，子 shell 在 `echo` 之前就退出，于是装上的是一个空 crontab。此后 `update` 因为文件哈希没有变化，不会再补装 cron。凡是经 init 或 init-aws 部署的节点，cron 都是空的。
— RUN-1 — runner 自更新时，用来改写路径的 sed 模式在渲染阶段也被替换掉了，导致新下载的 `reality_rotate.sh` 的 `DOCKER_DIR` 固定回 `/home/admin`。harden 后的影子用户、root、ubuntu 节点从第一次 cron 起就在 jq 处静默退出。
— XCUT-5 / DET-6 — runner 下载新脚本时没有用 `curl -f`，`404: Not Found` 或 `{"error":"Unauthorized"}` 这类错误正文都能通过 `bash -n`，结果覆盖正常脚本，之后 `exec` 返回 127。
— DET-4 — `reality_check` 在函数外使用了 `local`，只要 `SERVER_HOST` 是域名（也就是正常路径），体检就在 DNS 段崩溃，这是上一个提交引入的回归。
— DET-3 — SNI 判定失效后，脚本先发 Telegram 告警；告警一旦失败，`set -e` 就在扫描和换 SNI 之前终止整个流程。
— DET-7 / RUN-9 — 容器挂掉而重启又失败时，不会继续修复，也不会回滚；之后 cron 只看外部 SNI，Xray 一直宕着却被判为“无需更换”。

**根因三：真跑起来时会误判，并陷入轮换风暴**

— DET-2 / SEL-2 — 测量失败会被当成“SNI 已死”：境内 DNS 没有应答、`dig` 缺失、`reality-checker` 无法执行（它只有 x86-64 版本，ARM 主机上必然失败）都算。所谓“三级防误判”，其实只是同一个测量在 90 秒内重复三次。
— SEL-3 — 所有候选都失败时，兜底分支会不做任何验证、直接取备用池里第一个不等于当前 SNI 的域名；后面的“无可用 SNI”告警分支永远走不到。实验复现了两个备用域名每 15 分钟来回切换，每次都重置凭据并发出 4 条消息。
— SEL-6 / DET-8 — 本机回环探测只要失败一次，就绕过三次重试直接强制轮换。
— SEL-10 / BATCH-6 / DET-5 — 整条链路没有互斥锁：cron、`async_deploy` 和手动轮换可能同时执行，导致重复扫描、重复换密钥，已经推送出去的链接随即失效。
— SEL-5 — 备用池都是热门 CDN 大站，和 AWS 的 IP 明显不匹配，入选门槛又远低于扫描路径，实际上成了主路径。

**单台部署**

— INIT-1 — `./cnsr.sh init <别名> [IP]` 从来不给 `SSH_ALIAS` 和 `TARGET_IP` 赋值，位置参数在选项解析循环里被直接丢掉，单台部署每次都失败。init-aws 能用，只是因为它自己设置了这两个全局变量。
— GAP1-1 / GAP1-2 — 即使修好参数，非 harden 路径也把 SSH 端口写死为 22，并且每次都执行 `ufw --force reset`，会清掉宿主机原有的防火墙规则。sshd 不在 22 端口的 VPS 会被锁死。
— GAP1-4 — 生成伪装域名前，会删除 Cloudflare Zone 里所有指向本机 IP 的 A/AAAA 记录，而不看记录名。
— GAP1-6 — 等待 dpkg 锁 60 秒后，会对 apt、dpkg 和 unattended-upgrades 执行 `killall -9`，并删除锁文件。
— INIT-9 — `local X=$(generate_cf_domain ... | tail -n 1)` 吞掉了 DNS 创建失败，错误提示文字可能被当作域名下发到节点。
— INIT-11 — 远端步骤都无条件使用 sudo，root 登录且没装 sudo 的最小化 Debian 上会整体失败。

**批量部署**

— RUN-2 — `--detach` 用 `$0` 重新执行自己时丢掉了 `init-aws` 子命令，子进程以“未知命令: -f”退出，前台却显示“已转入后台”。
— BATCH-4 — `cnsr.sh` 的 `set -e` 会传进 Phase 1 的子 shell，任何一台创建失败，worker 都写不出 `_aws.err`，而主循环没有超时，会永久卡住。这与日志里停在“正在通过 AWS API 创建实例”的现象一致。
— INIT-4 — 批量模式在 `if module_init` 中调用初始化函数，函数内部的 errexit 因此失效，加上大量 `|| true`，部署失败也一律报告成功。
— BATCH-8 — AAAA 记录创建失败会让整个伪装域名作废，A 记录变成孤儿，节点退回裸 IP，正是日志里那次 Cloudflare 报错的后果。
— BATCH-9 — Phase 2 的统计不可靠：`*.err` 通配把 Phase 1 的失败也计入，超时后也不终止 worker。
— BATCH-7 — `destroy-aws` 即使一个实例都没匹配到，也会删除 SSH 配置和 Cloudflare 记录，而且通配删除前不预览、不确认。
— GAP1-5 — `aws.py create` 遇到同名实例会直接“认领”，并覆盖它的整个 Lightsail 防火墙。

**加固**

— INIT-3 / HARD-1 — 在 Lightsail 上用 `--harden` 一定会锁死主机：先把 sshd 切到随机端口并删掉 22，再通过这个被云防火墙拦着的新端口去探测区域、开放端口，这一步永远连不上。
— GAP2-3 — 放行新端口调用的 API 本身也不存在：boto3 里没有 `open_instance_port`，AWS CLI 也没有 `open-instance-port`。单元测试用 MagicMock 掩盖了这一点。
— HARD-3 — 加固缺少“先验证、后切断”：重启失败、新端口没有监听、影子用户的 `authorized_keys` 为空时，照样删掉 22 并报告成功，也没有回滚机制。
— HARD-4 / HARD-5 — Ubuntu 22.10 及以上使用 `ssh.socket`，只改 Port 并不生效；`sshd_config.d` 下的 drop-in 还可能覆盖密码登录和 root 登录的设置。
— HARD-8 / HARD-10 / HARD-11 — fail2ban 仍然守着 22 端口；`IP_STACK=ipv4` 时 IPv6 入站完全放开；Docker 发布的端口会绕过 UFW。
— HARD-6 / SCAN-2 — “零凭据”名不副实：直连模式把可写仓库的 `GH_TOKEN` 推到了节点上；`GATEWAY_AUTH_KEY` 为空时，网关的鉴权整个失效（fail-open）。

**测试为什么没拦住**

— XCUT-13 — `core/init.sh` 和 `core/print.sh` 没有任何测试执行过，连 `bash -n` 都没跑。`module_init`、批量编排、`--detach`、`async_deploy` 和 `reality_rotate` 的主流程也都没有执行测试，部分用例是在测试里重新实现一遍逻辑再断言自身。
— XCUT-16 — 有测试会读写仓库里真实的 `.env`，进程被中途杀掉时，真实凭据会被 mock 值覆盖。`test_cnsr_update_command_dispatch` 还会在没有 `.env` 时自动生成一个。

**Codex 独有结论**

Codex 盲审报告了 28 条，大部分与工作流的结论独立重合。只有它报告的 7 条，各由 2 名反驳者复核，结果如下。

| 编号 | 结论 | 复核结果 | 严重度 |
| :--- | :--- | :--- | :--- |
| CX-1 | 网关转发的扫描参数被直接拼进 `scan.yml` 的 `run:`，存在脚本注入；runner 有 `contents: write` 并会持久化 token，可以改写 main 上的模板，各节点 cron 随后会拉取并执行 | 成立，已在本地复现 | high |
| CX-5 | `aws.py` 吞掉 `put_instance_public_ports` 的失败，云端 443 没放行却报告成功，`cnsr check` 还会把它误诊为 SNI 阻断 | 成立，与 BATCH-12 合并并升级 | medium |
| CX-4 | Lightsail 的 key pair 与本地 SSH 身份分别选择，互不核对；非 TTY 或 `--detach` 时会静默取 agent 里的第一把密钥 | 成立，需要配置错误才会触发 | medium |
| CX-6 | `get_instance` 连续 20 次抛异常后 `inst` 未赋值，真实的 AWS 错误被掩盖 | 成立 | low |
| CX-7 | 新凭据没有校验：UUID 管道掩盖了 `compose run` 的失败，可能把空 UUID 写进正式配置且不回滚 | 成立，但触发面窄 | low |
| CX-2 | 加固会把已有账号提升为免密 root | 不成立：同名账号只可能是 cnsr 自己之前建的；残余的锁死风险已并入 HARD-3 | — |
| CX-3 | init 和换域名时删除主机指纹，破坏了 host key 校验 | 不成立：实际只多出一次短暂的 TOFU 窗口 | — |

CX-1 的利用前提是先拿到 `GATEWAY_AUTH_KEY`（攻下任一节点即可），或者 Worker 没有配置这个 key。它的意义在于打穿了“网关模式下节点零凭据”的设计边界：攻下一个节点，就能把权限扩大到仓库写入和全部节点。

**修复路线建议**

| 阶段 | 目标 | 主要条目 | 性质 |
| :--- | :--- | :--- | :--- |
| P0 | 让基本流程真的能跑 | INIT-1、RUN-2、INIT-2、RUN-1、DET-4、BATCH-4、DET-3、XCUT-5，以及先禁用 Lightsail 上的 `--harden` | 小改动，逐条先写失败测试 |
| P1 | 自愈不再乱来 | 互斥锁；把测量失败与 SNI 失效分开（三态判定）；取消未经验证的兜底；凭据校验、`xray -test` 加回滚；修复容器 | 中等改动 |
| P2 | 自愈真正有效 | 境内视角的探测来源；SNI 轮换与身份轮换解耦；可自动更新的订阅交付；IP 级补救自动化；IPv6 数据面 | 需要先做设计决策 |
| P3 | 部署与加固重做 | 先验证后切断并可回滚；sshd drop-in；非破坏性防火墙；幂等；Actions 注入与网关 fail-open；每节点独立密钥 | 较大重构 |

P2 绕不开几个只有你能回答的问题：有没有可用的境内探测点（家里的路由器、NAS、手机或一台境内小机器）？客户端能否使用订阅 URL 自动更新？封 IP 后是否允许自动换 IP（每次都会产生一个静态 IP 配额和 DNS 变更）？

**补充取证：SNI 一开始就没筛出来（2026-10-16）**

用 gh 只读地查看了扫描 Action 的运行记录和 Release CSV，又在 `prod-us` 的临时目录里用真实的 reality-checker 复现了节点端的筛选。

— Action 本身正常 — 326 次扫描全部成功，单次约 11 秒，在节点所在的 /22 里找到 3 到 84 个满足 TLS 1.3、h2、X25519 的站点。IPv6 部分始终为 0，与 C03 一致。
— 候选多少取决于节点运气 — 抽查的 8 个节点里有 4 个的 /22 很稀疏，扫描结果只有 3 到 8 行。经过节点端“CDN 为无、4 星以上、HTTP 200”的筛选后只剩 0 到 1 个，于是退回写死的苹果、微软备用池（R01），而这些大站和 AWS 的 IP 明显不匹配。
— 能通过的候选质量也存疑 — 通过的多是 staging 站、小机构站点，例如 `stg-it.com`、`staging.coreus.jp`。扫描结果里还混有 binance.com、okx.com 这类被墙域名，好在 checker 的黑名单把它们挡住了。
— 9 月 11 日 fg_jp-aws 的轮换风暴 — 05:30 到 07:30 几乎每 15 分钟触发一次扫描，与 S02 相符。
— 公开仓库暴露节点信息 — 仓库是 PUBLIC。Release 里的 CSV 和 Actions 日志会公开每个节点的别名、所在 /22 和扫描时间。
— 局限 — checker 是从美国的 `prod-us` 发起探测，不是从日本节点，所以“网络不可达”的数量可能有出入。境内 DNS 投毒这一关没有复现，因为 `prod-us` 上没有 dig。

**区域候选池验证（2026-10-16）**

— 东京模拟 — 把已有 8 个 AWS 东京 /22 的 checker 结果合并成一个池。按现有筛选条件、并剔除测试站后剩 17 个候选，适当放宽条件后有 50 个。而单个节点只用自己的 /22 时，有 3 个节点一个都没有。
— 小厂商实测 — 手动触发现有扫描 Action，扫与 `prod-us` 同属一家上游的一个 /20 地址块（不包含它自己，厂商与网段见私密笔记）。40 秒扫出 266 个站点，第一道过滤后剩 102 个；在 `prod-us` 上用 checker 验证，69 个适合，33 个通过节点筛选。
— 小厂商网段的候选信誉差 — 通过的 33 个里至少 12 个明显是代理面板、动态域名或个人工具（`panel.fzero.qzz.io`、`*.duckdns.org`、`aiapi.frp-lax01.whaty.org` 等）。扫描结果里还有大量 Cloudflare Origin 证书、localhost、自签名证书，以及别人 REALITY 节点转发出来的 apple.com、yahoo.com。AWS 网段的邻居则多是正规企业站点。
— Actions 的 secret 全是空的 — `TG_BOT_TOKEN`、`TG_CHAT_ID`、`GATEWAY_URL`、`GATEWAY_AUTH_KEY` 都没有配置。所以“扫描完成”的 Telegram 通知从未发出，写入 KV 的那一步也从未执行，节点一直靠网关回退去读公开 Release。
