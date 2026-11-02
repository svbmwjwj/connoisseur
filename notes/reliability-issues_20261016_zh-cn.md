###### cnsr 去重问题清单

由 134 条复核成立的审计结论合并而成，共 82 个问题，按严重度排序。可交互版本见 https://claude.ai/artifact/Rrxbbux9JFhvKH5E4nLumS。

**A01 — `init-aws ... --detach` 在后台什么也没部署，终端和 Telegram 却说“已启动”**

— 属性 — critical · AWS 自动部署 · AWS 路径 · 工作量 S
— 问题 — --detach 用 `nohup "$0" "${FILTERED_ARGS[@]}"` 重新执行 cnsr.sh，但保存下来的参数里没有 init-aws 子命令，子进程把 -f 或别名当成命令，立刻以“未知命令”退出。父进程不确认子进程是否还活着，就发出了“已启动”通知。
— 现象 — 终端显示“批量部署已转入后台”，TG 收到“AWS 批量部署已启动”，但一台实例也没创建。只有 logs/deploy_*.log 里有一行“未知命令: -f”。
— 修复方向 — 重新执行时显式带上 init-aws 子命令和 cnsr.sh 的绝对路径；父进程等 1-2 秒，确认子进程还在运行后再发通知；补一条参数重组测试。
— 位置 — `core/init_aws.sh:25`、`core/init_aws.sh:165-201`、`cnsr.sh:42-43`
— 合并自 — RUN-2、BATCH-2、XCUT-3

**H01 — 在 Lightsail 上用 --harden 一定会把主机锁死**

— 属性 — critical · 加固 · AWS 路径 · 工作量 M
— 问题 — 加固的顺序是：先把 sshd 改到随机端口、删掉 UFW 里的 22、只允许影子用户登录并重启 sshd，然后才“通过新端口”去探测 AWS 区域，再调 API 给云防火墙放行新端口。可此时新端口正被 Lightsail 防火墙拦着，这一步永远连不上，是个死循环。这也说明，在已经有云安全组的 AWS 路径上再叠加主机 SSH 加固，既多余又危险。
— 现象 — init-aws --harden 打印“深度安全加固完成”后，后续每次 ssh 都要卡约 75 秒才超时。节点上没有 Docker/Xray，也没有 cron；批量模式下 300 秒后被记为超时。22 端口、新端口和 Lightsail 网页 SSH 都登不上，只能手动去控制台放行那个随机端口才能救回来。
— 修复方向 — AWS 路径直接不做 SSH 加固，由云防火墙负责收口。如果要保留，就先在本地用已知的区域和实例名调 API 放行新端口，让新旧端口同时监听，确认新端口能登录后再关 22，失败时自动回滚。
— 位置 — `lib/security.sh:185-224`、`lib/security.sh:258-264`、`lib/security.sh:273-274`、`lib/security.sh:305-330`
— 合并自 — INIT-3、BATCH-1、HARD-1、XCUT-2

**L01 — 新部署的节点上没有 cron 定时任务，自愈和 SNI 轮换从没运行过**

— 属性 — critical · 自愈运行机制 · 本地共用 · 工作量 S
— 问题 — Docker 步骤在 `set -e` 下用 `(crontab -l | grep -v runner.sh; echo ...) | crontab -` 重装 cron。如果 crontab 里只有同步阶段写入的那条 runner，grep 输出为空并返回 1，子 shell 在 echo 之前就退出了，结果写入的是一个空 crontab，runner 任务被清掉。安装后不检查结果，update 在文件哈希没变时也不补装 cron，rotate.log 每次还会被覆盖，所以这个状态会一直持续，也很难事后排查。
— 现象 — 节点显示部署成功，但 SNI 被封后从不自动更换。只有恰好在模板改动后执行过 update/check/rotate-sni 的节点才会偶然恢复，看起来就是“自动轮换时好时坏”。
— 修复方向 — 改用不受 errexit 影响的幂等写法（或写入 /etc/cron.d/cnsr-<alias>），装完在远端用 `crontab -l | grep -q runner.sh` 校验，并让 update/check 每次都检查 cron，缺了就补装。
— 位置 — `core/init.sh:578-579`、`core/update.sh:235-243`、`core/update.sh:249-255`
— 合并自 — INIT-2、RUN-16

**L02 — 用 root、ubuntu 或加固影子用户部署的节点，自愈脚本在第一次 cron 后就坏掉**

— 属性 — critical · 自愈运行机制 · 节点端 · 工作量 S
— 问题 — 网关模式或 GH_TOKEN 模式下，runner.sh 每 15 分钟下载新版 reality_rotate，靠把字面量 /home/admin/docker-apps/xray 替换成真实目录。可是 update 渲染 runner.sh 时，已经把这条替换规则里的字面量本身换掉了，所以下载下来的脚本仍然写着 /home/admin。部署用户不是 admin 时，脚本找不到 tg_templates 和 config，在 jq 那一步直接退出。
— 现象 — root 登录的 VPS、Ubuntu 镜像或 --harden 节点，部署后不到 15 分钟自愈就停了：rotate.log 只有一行 jq 报错，SNI 不再轮换，TG 也没有任何消息。如果这次 cron 赶在首轮配置生成之前，xray 会一直停在占位配置上反复崩溃重启。执行 update 也修不好。
— 修复方向 — 模板里改用单独的占位符，或者让 reality_rotate.sh 根据自身所在目录推导 DOCKER_DIR，不再依赖会被二次替换的路径字面量，并补一个非 /home/admin 目录的回归测试。
— 位置 — `templates/runner.template.sh:4`、`templates/runner.template.sh:36`、`core/update.sh:89`、`core/update.sh:153`
— 合并自 — RUN-1

**S01 — 节点在国内已经被封，自愈却判断“一切正常”：检测只看服务器自己，看不到境内的阻断**

— 属性 — critical · SNI 失效检测 · 节点端 · 工作量 L
— 问题 — cron 的健康检查全在 VPS 上做：查境内 DNS、从 VPS 连 dest 站点、用回环测本机 443，从来不测“境内客户端 → 节点IP:443 + 当前 SNI”这条真实路径。因此端口级封锁和 SNI 级 RST（REALITY 最常遇到的封锁方式）完全看不到；唯一有境内视角的握手探针只在手动 cnsr check 里，不参与自动决策。此外，自愈手段只有换 SNI，没有任何自动换 IP 的路径，IP 被封只能靠人发现。
— 现象 — 客户端已经连不上，rotate.log 每 15 分钟仍写“恢复正常，无需更换”，既不告警也不轮换。真正触发轮换的反而多是 dest 站点自身的波动或测量故障，告警文案却写“已被阻断”，让人误以为系统识别出了 GFW 封锁。
— 修复方向 — 引入境内视角的探测（境内探针、拨测 API 或客户端回报）并回传网关，按失败类型分开处理：IP/端口不通就告警，并建议或触发换 IP；只有 SNI 被 RST 才换 SNI。同时修正告警文案。
— 位置 — `templates/reality_rotate.template.sh:154-184`、`templates/reality_rotate.template.sh:197-227`、`templates/reality_rotate.template.sh:251-294`、`templates/reality_check.template.sh:126-152`、`core/check.sh:113-119`
— 合并自 — DET-1、SEL-1、GAP3-10

**V01 — `./cnsr.sh init <别名> <IP>` 根本跑不起来：别名和 IP 参数被丢掉了**

— 属性 — critical · 通用 VPS 部署 · 通用 VPS 路径 · 工作量 S
— 问题 — cnsr.sh 把别名和 IP 传给 module_init，但这个函数只解析 `--harden` 这类选项，其余位置参数都被直接 shift 掉，SSH_ALIAS 和 TARGET_IP 始终为空。init-aws 能用，只是因为它在调用前先设好了这两个全局变量。所以通用 VPS 的单机部署（包括 --harden）从没真正执行过；修好之后，V09、H05、V04、V11 等一批潜伏的 VPS 路径问题才会暴露出来。
— 现象 — 按 README 示例执行后，第一行显示“开始初始化新节点: ”，别名是空的，随后报“免密安全接管失败！请检查公钥状态”并退出。
— 修复方向 — 在 module_init 开头显式读取位置参数（第一个是别名，第二个是 IP），init-aws 也改为传参，再补一条经 cnsr.sh 入口调用的端到端测试。
— 位置 — `cnsr.sh:69`、`cnsr.sh:81-83`、`core/init.sh:28-63`
— 合并自 — INIT-1、BATCH-3、HARD-2、XCUT-1

**A02 — 批量部署和 update 把失败也报告成成功**

— 属性 — high · AWS 自动部署 · 本地共用 · 工作量 M
— 问题 — 部署流程的错误处理全靠隐式的 `set -e`，但批量模式是在 `if module_init ...` 里调用的，Bash 在条件判断里会关掉 errexit。再加上大量 `|| true` 和不检查返回码的 scp/ssh，任何一步失败都会继续往下走，最后返回成功。结果同一个函数在单机和批量、update 和 check 下的失败行为互相矛盾，测试也没有在 set -e 下运行。
— 现象 — 批量部署时 docker 没装上、xray 没起来、async_deploy 没投递，进度条照样显示成功，并打印“阶段一：服务器基础环境搭建完成”。`./cnsr.sh update` 对完全连不上的节点也报“热更新完成”。而 `check "jp_*"` 遇到第一个出问题的节点就无声中止。
— 修复方向 — 不再依赖隐式 errexit：每个远端步骤都显式检查返回码并 return 1；阶段一结束前在远端验收 docker、xray 容器、cron 和 async_deploy 都在，才算成功。
— 位置 — `core/init_aws.sh:662`、`core/init.sh:577`、`core/init.sh:595-598`、`core/update.sh:236`、`core/update.sh:301`、`core/check.sh:175-179`
— 合并自 — INIT-4、XCUT-10

**A03 — 批量创建时只要一台实例创建失败，整个部署就永远卡在进度条上**

— 属性 — high · AWS 自动部署 · AWS 路径 · 工作量 S
— 问题 — cnsr.sh 打开的 `set -e` 会被批量 Phase 1 的后台子 shell 继承。`py_out=$(uv run providers/aws.py create ...)` 一返回非零，子 shell 就在这一行退出，既不打印错误，也不写 `_aws.err` 标记。主循环只数标记文件、没有超时，INT/TERM trap 又不退出，所以连 Ctrl-C 都停不下来。
— 现象 — 进度条一直停在“0/N 实例创建与公网 IP 分配中...”。logs/init_aws_<alias>.log 只有一行“正在通过 AWS API 创建实例”，报错内容全丢了；其余已经建好的实例也进不了 Phase 2，没有任何 TG 告警。
— 修复方向 — worker 里改成 `py_out=$(...) || status=$?`，并在 EXIT trap 里无条件写结果标记；Phase 1 主循环加超时，用 wait 拿到真实退出码。
— 位置 — `cnsr.sh:4`、`core/init_aws.sh:480-538`
— 合并自 — BATCH-4、XCUT-7

**H02 — 加固不“先验证再切断”，也没有回滚，任何一步出错都可能把自己锁在门外**

— 属性 — high · 加固 · 本地共用 · 工作量 M
— 问题 — 加固直接删掉 22 的放行、收紧 AllowUsers，却不先确认新端口真的在监听、影子用户的 authorized_keys 不为空、新连接能登录。sshd 重启失败被 `|| true` 吞掉，备份在语法检查通过后就删了。只要云安全组没放行随机端口（GCP、Oracle、腾讯云等默认拒绝的平台），或者原本不是靠 authorized_keys 登录，当前会话一断，主机就进不去了；这是通用 VPS 路径保留加固时最先要补的安全网。
— 现象 — CLI 照样打印“深度安全加固完成”，之后所有 ssh 都连不上，只能去厂商控制台救援。
— 修复方向 — 加固前先挂一个定时回滚任务（例如 systemd-run 180 秒后恢复备份），让新旧端口并存；确认 sshd -T 和端口监听正常、并用新端口加影子用户实际登录成功后，再取消回滚、关闭 22；authorized_keys 为空时直接中止。
— 位置 — `lib/security.sh:170-178`、`lib/security.sh:194`、`lib/security.sh:226-234`、`lib/security.sh:258-264`
— 合并自 — HARD-3

**H03 — 给 Lightsail 云防火墙放行新 SSH 端口时调用了不存在的 API，单元测试却是绿的**

— 属性 — high · 加固 · AWS 路径 · 工作量 S
— 问题 — providers/aws.py 调用的 open_instance_port 在 boto3 里不存在，security.sh 用的 AWS CLI 子命令 open-instance-port 也不存在，正确的是 open_instance_public_ports / open-instance-public-ports。单测用的是不带 spec 的 MagicMock，调用任何方法都会“成功”，把问题掩盖了。所以就算修好了 H01 的顺序问题，--harden 在 Lightsail 上照样会锁死。
— 现象 — 终端照样打印“深度安全加固完成”，但云防火墙上根本没有新端口，节点失联。
— 修复方向 — 改用 open_instance_public_ports（CLI 是 open-instance-public-ports），并显式传入 cidrs 和 ipv6Cidrs；放行失败时中止加固；测试改用 botocore Stubber 或 create_autospec。
— 位置 — `providers/aws.py:356`、`lib/security.sh:317`、`lib/security.sh:323`、`tests/test_aws_provider.py:227`
— 合并自 — GAP2-3

**K01 — init-aws 部署完收不到节点链接（只建一台也一样）**

— 属性 — high · 凭据交付 · AWS 路径 · 工作量 M
— 问题 — init-aws 一律走批量流程，并把 BATCH_MODE 写进节点的 .env，所以节点首轮生成配置时不推送。本地的汇总 print 在 module_init 返回后立刻执行，可这时 async_deploy 还没生成 vless.txt。两边都没送出链接，用户只能等之后真发生一次轮换，或者手动 print。
— 现象 — TG 先收到“批量部署全部完成……节点订阅链接已紧随其后拆分推送”，之后却一条链接都没有。终端最后报“未能从任何节点提取到配置文件”，以 exit 1 结束。必须过几分钟手动执行 `./cnsr.sh print "<pattern>" --tg`。
— 修复方向 — 汇总改为本地轮询各节点的 vless.txt（带超时），就绪后再推送；或者让节点在批量模式下完成后上报网关，由网关汇总。BATCH_MODE 不要一直留在节点 .env 里，并修正“已推送”的文案。
— 位置 — `lib/security.sh:24-26`、`core/init_aws.sh:649`、`core/init.sh:605`、`templates/reality_rotate.template.sh:596-597`、`templates/async_deploy.template.sh:127`
— 合并自 — RUN-7、BATCH-5、XCUT-8

**K02 — 每次自动轮换都会让所有客户端失效，只能靠一条 TG 消息手动重新导入**

— 属性 — high · 凭据交付 · 节点端 · 工作量 L
— 问题 — 每次自动轮换都会重新生成 UUID、私钥和 shortId，serverNames 只保留新 SNI，并重启容器断开所有连接。项目没有订阅端点这类自动下发通道，新配置只靠一条 TG 消息送达。再加上误判轮换和轮换风暴，客户端会被反复打断。
— 现象 — 一旦发生轮换，已导入的链接全部失效。如果 TG 推送失败、被批量模式静默，或者用户没看到消息，节点在用户眼里就是“轮换后彻底不能用了”。
— 修复方向 — 自动流程只换 SNI，保留 UUID、密钥和 shortId；提供带 token 的订阅端点（例如节点把最新配置写进网关 KV，由 /sub/<alias> 输出）；凭据轮换只在手动操作或确认泄露时进行。
— 位置 — `templates/reality_rotate.template.sh:523-530`、`templates/reality_rotate.template.sh:547-568`、`templates/reality_rotate.template.sh:586-603`
— 合并自 — RUN-5

**L03 — 新节点部署期间 cron 与首轮部署并发轮换，用户收到两套凭据、其中一套失效（修好 L01 后会立刻出现）**

— 属性 — high · 自愈运行机制 · 节点端 · 工作量 M
— 问题 — cron 在同步脚本阶段就装好了，比真实配置生成得早；整条自愈链路没有互斥锁，cron 的轮换会和 async_deploy 的 --init 轮换同时进行，两个进程共用 config.json.tmp 和 CSV、各自生成凭据，谁后写谁生效，curl 没有总超时，慢的那次还会被后续 cron 叠加上去。目前在 crontab 原本为空的全新节点上，Docker 步骤会按 L01 把 cron 清空，所以部署期并发暂时被掩盖；但只要修好 L01，或主机本来就有别的定时任务，或之后执行过一次有变更的 update，这个问题就会出现，因此 L01 和 L03 必须一起修。
— 现象 — 修好 cron 之后（或在已有其他定时任务的主机上），新节点在头 15 分钟内被轮换两次，TG 先后收到“部署完成”和“配置换新”两套凭据，其中一套导入后连不上；手动 rotate-sni 与 cron 重叠时也会这样。
— 修复方向 — reality_rotate 开头用 flock 加互斥锁（async_deploy、rotate-sni、test-sni 共用），并把 cron 安装挪到 async_deploy 成功之后，或在检测到占位配置时让非 --init 运行直接退出。
— 位置 — `core/init.sh:496`、`core/update.sh:242`、`core/init.sh:579`、`core/init.sh:605`、`templates/reality_rotate.template.sh:151`、`templates/reality_rotate.template.sh:547-568`、`templates/async_deploy.template.sh:85-130`、`templates/runner.template.sh:47`
— 合并自 — DET-5、SEL-10、RUN-6、BATCH-6

**L04 — 网关或 GitHub 返回错误页时，节点会把错误页当成新的自愈脚本装上**

— 属性 — high · 自愈运行机制 · 节点端 · 工作量 S
— 问题 — runner.sh 下载新版 reality_rotate 时没加 curl -f，也不看 HTTP 状态，只要求文件非空、能通过 bash -n。“404: Not Found”或 401 的单行 JSON 恰好是合法的 bash 语法，于是好脚本被覆盖，执行时返回 127；curl 还没有总超时。如果错误一直存在（GATEWAY_AUTH_KEY 不一致、Worker 的 GH_TOKEN 过期而仓库是私有的、模板在 main 上被改名），所有节点的自愈会同时、永久地失效。
— 现象 — rotate.log 里只有一行“404:: command not found”之类的输出，TG 没有任何告警，SNI 自动轮换悄悄停了。网关恢复后，下一轮 cron 才会自己好起来。
— 修复方向 — 下载改用 `curl -fsS --max-time`，校验首行 shebang 和模板里的固定标记（最好再校验 sha256），任何一步失败都保留并执行旧脚本。
— 位置 — `templates/runner.template.sh:21-27`、`templates/runner.template.sh:30-47`、`gateway/worker.js:14-20`、`gateway/worker.js:82-93`
— 合并自 — XCUT-5、DET-6、RUN-4、SCAN-1、HARD-7

**S02 — 检测工具自己出故障也被当成“SNI 已死”，节点陷入每 15 分钟一次的轮换风暴**

— 属性 — high · SNI 失效检测 · 节点端 · 工作量 M
— 问题 — 境内 DNS 没有应答、缺 dig、reality-checker 跑不起来（它只有 x86-64 版本，ARM 主机上一定失败），这些“测量失败”都被当成 SNI 失效。扫描结果和备用池全部判为不合格后，兜底分支不做任何验证，直接选备用池里第一个与当前不同的域名，所以真正的“无可用 SNI”告警分支永远走不到。结果节点就在备用池的前两项之间来回切换。
— 现象 — 节点大约每 15 分钟换一次 SNI 和全套凭据（例如在 gateway.icloud.com 和 swdist.apple.com 之间来回），客户端手里的配置永远是过期的。TG 被阻断告警、新配置、体检报告和扫描完成消息刷屏，GitHub Actions 每天被触发约 96 次。
— 修复方向 — 把“测量失败”和“测得失效”分开：依赖或探针不可用时只告警、不轮换；兜底域名也必须通过验证，不通过就保留现有配置并告警；再加轮换频率上限，并按 CPU 架构下发 checker。
— 位置 — `templates/reality_rotate.template.sh:163-175`、`templates/reality_rotate.template.sh:211-226`、`templates/reality_rotate.template.sh:489-518`
— 合并自 — DET-2、SEL-3

**S03 — 使用域名的节点，体检一定会中途崩溃：cnsr check 报异常，轮换后收不到体检报告**

— 属性 — high · SNI 失效检测 · 节点端 · 工作量 S
— 问题 — reality_check.sh 在函数外面用了 `local`，bash 会报错并返回非零，在 set -e 下直接退出，而 bash -n 检查不出这种错误。只要 SERVER_HOST 是域名（这是正常情况），后面的 SNI 检查、系统检查、TG 报告和 health.json 都不会执行。这是 HEAD 新引入的回归。
— 现象 — `./cnsr.sh check <alias>` 打印到 DNS 解析那段就报“远端体检执行异常 (退出码: 1)”，通配符批量 check 在第一个节点就停了。轮换后的自动体检静默失败，批量模式的 --notify-on-error 永远不会报错，本地握手探针即使测到 BLOCKED 也给不出假死结论。
— 修复方向 — 去掉顶层的 local，改成普通变量；在 CI 里加 shellcheck（SC2168 能直接查出来），并加一条 SERVER_HOST 为域名的执行测试。
— 位置 — `templates/reality_check.template.sh:6`、`templates/reality_check.template.sh:225-252`、`core/check.sh:98-123`
— 合并自 — DET-4、XCUT-6、RUN-8

**V02 — 访问双栈网站时部分连接随机失败或变慢：Xray 会去用容器里根本没有的 IPv6**

— 属性 — high · 通用 VPS 部署 · 节点端 · 工作量 S
— 问题 — Xray 出站的 DNS 和 freedom 都设成了 UseIP，会解析并尝试 AAAA 地址；但已提交的 compose 里，容器没有 IPv6 路由，凡是选中 IPv6 的连接必然失败。TCP 能靠重试挽回一部分，UDP/QUIC 会话一旦第一次选中 IPv6，整个会话都会失败，自愈环节对此完全没有反应。
— 现象 — 访问 Google、YouTube、Cloudflare 系等双栈站点时，单条新连接约 3% 直接失败，约 22% 多出 100–600ms 延迟；一个有 30 条连接的页面，至少一条失败的概率约 61%。游戏、语音这类 UDP 应用直接用不了，很容易被误以为是 SNI 或线路问题。
— 修复方向 — 在容器真正有 IPv6 出口之前，把 dns.queryStrategy 改成 UseIPv4（或 UseSystem），freedom.domainStrategy 改成 UseIPv4v6；已部署的节点需要单独下发新的 config。
— 位置 — `templates/config.json.template:23`、`templates/config.json.template:79`、`templates/compose.yml.template:6`、`core/init.sh:499`
— 合并自 — GAP2-2

**X01 — 拿到网关密钥的人能在 GitHub Actions 里执行任意命令，进而改写所有节点的自愈脚本**

— 属性 — high · 安全 · 节点端 · 工作量 S
— 问题 — 节点经网关提交的扫描参数被 Worker 原样转发，scan.yml 再把 target_ip 等参数直接拼进 shell 源码，参数里的 $(...) 会被执行。actions/checkout 默认把有 contents:write 权限的 GITHUB_TOKEN 留在 .git/config 里，注入的代码可以直接 push 修改 templates/reality_rotate.template.sh，所有节点的 runner 会在 15 分钟内拉下来执行。前提是攻击者先拿到 GATEWAY_AUTH_KEY（攻破任一节点或拿到其 .env），或者 Worker 根本没配这个密钥。
— 现象 — 平时没有任何感觉；但只要有一个节点被攻破，攻击者就能借 CI 拿下全部节点。
— 修复方向 — scan.yml 改为通过步骤的 env 传参，并严格校验 IP、CIDR、别名、时间戳的格式；checkout 设置 persist-credentials: false，把发布产物的写权限和节点触发的扫描任务分开。
— 位置 — `.github/workflows/scan.yml:31`、`.github/workflows/scan.yml:43-47`、`gateway/worker.js:15`、`gateway/worker.js:61`、`lib/security.sh:24`
— 合并自 — CX-1

**X02 — 所谓“零凭据”节点，手里其实有能影响整个节点集群的密钥**

— 属性 — high · 安全 · 本地共用 · 工作量 L
— 问题 — 直连模式会把带仓库写权限的 GH_TOKEN 下发到节点的 .env。网关模式下，所有节点和 CI 共用同一把 GATEWAY_AUTH_KEY，谁拿到它都能写入任意节点的 SNI 扫描结果、触发 Actions、借机器人发消息。权限没有按节点隔离。
— 现象 — 任何一个节点被攻破或 .env 泄露，攻击者就能给所有节点投毒 SNI 候选、刷爆 Actions 配额；在直连模式下还能借仓库写权限拿下全部节点。
— 修复方向 — 节点一律走网关，不再下发 GH_TOKEN 和 TG_BOT_TOKEN；网关为每个节点签发只读、只限本别名的 token，KV 写入只接受 CI 专用密钥；.env 下发后执行 chmod 600。
— 位置 — `lib/security.sh:20-33`、`gateway/worker.js:14-20`、`gateway/worker.js:50-79`、`gateway/worker.js:96-115`
— 合并自 — HARD-6

**X03 — 没配 GATEWAY_AUTH_KEY 时，网关的所有接口对公网完全开放，任何知道 Worker 地址的人都能借 X01 控制全部节点**

— 属性 — high · 安全 · 节点端 · 工作量 S
— 问题 — 密钥为空时，Worker 直接跳过鉴权（fail-open，测试把它当成“可选鉴权”的正常行为），任何知道 Worker URL 的人都能触发 Actions、读取私有 Release 资产、冒充机器人发 TG，还能写入不带时间戳的 `csv:${alias}.csv`。更严重的是，这正好去掉了 X01 的前提：无需任何密钥就能经 /api/gh-dispatch 把命令注入 scan.yml，改写 main 上的自愈模板，所有节点会在 15 分钟内拉下来执行。因此严重度应与 X01 持平，从 medium 调为 high。
— 现象 — 平时看不出异常；一旦 Worker 地址泄露，会出现来历不明的 Actions 运行、陌生的 TG 消息，甚至 main 分支上出现不是自己提交的模板改动。
— 修复方向 — 鉴权改为 fail-closed：没有配置 GATEWAY_AUTH_KEY 时，拒绝所有触发、写入和读取类请求，并在部署检查中把缺密钥当成错误。
— 位置 — `gateway/worker.js:15`、`gateway/worker.js:51`、`gateway/worker.js:97`、`gateway/worker.js:102`
— 合并自 — SCAN-2

**A04 — Lightsail 云防火墙放行 443 失败时被悄悄忽略，节点“部署成功”，外面却连不上**

— 属性 — medium · AWS 自动部署 · AWS 路径 · 工作量 S
— 问题 — providers/aws.py 调用 put_instance_public_ports 时写的是 `except Exception: pass`，事后也不用 get_instance_port_states 核对，返回的 JSON 里没有防火墙状态。botocore 会自动重试瞬时错误，真正被吞掉的主要是 IAM 缺权限这类不可重试的 4xx；失败时实例保留默认的 22/80，SSH 部署和订阅推送照常完成，但 443 是关着的。另外，用单机 init 接管 Lightsail 实例时完全不碰云防火墙（sync_firewall 没有任何调用方）。
— 现象 — 节点显示部署成功、容器也在运行，客户端却完全连不上。唯一的外部检测 cnsr check 还会把它误报成 GFW/SNI 封锁，把人引向无效的 rotate-sni。
— 修复方向 — 去掉吞异常的写法，显式传入 cidrs 和 ipv6Cidrs；调用后用 get_instance_port_states 校验 443 的 TCP/UDP 在 IPv4/IPv6 上都已放行，失败就返回非零并告警。
— 位置 — `providers/aws.py:168-189`、`providers/aws.py:362`、`core/init_aws.sh:488`
— 合并自 — GAP2-6、BATCH-12、CX-5

**A05 — init-aws 在云端和本地各选各的 SSH 密钥，选错了整批实例都登不上**

— 属性 — medium · AWS 自动部署 · AWS 路径 · 工作量 M
— 问题 — 云端用模板里的 KEY 创建实例（为空就用区域默认密钥对）；本地则按名字去 agent 或 ~/.ssh 下找文件，找不到时，在非 TTY、--detach 或 agent 只有一把密钥的情况下，静默取第一把。两边从不比对指纹，init 又用 IdentitiesOnly=yes 只出示这一把；KEY 为空时，也不会去找 LightsailDefaultKey-*.pem。
— 现象 — 实例和 IP 都创建成功了，但整批 SSH 探活失败，实例不会被回收，一直在计费。
— 修复方向 — 把云端 key pair 和本地公钥当成同一个身份来校验（比对指纹），显式指定了却匹配不上时立刻失败，不要悄悄换一把钥匙。
— 位置 — `core/init_aws.sh:383-420`、`core/init_aws.sh:486`、`core/init_aws.sh:660`、`providers/aws.py:120`、`core/init.sh:292`
— 合并自 — CX-4

**A06 — 批量部署的成功/失败统计不可靠：要白等 5 分钟，失败原因还被统一标成“超时”**

— 属性 — medium · AWS 自动部署 · AWS 路径 · 工作量 M
— 问题 — module_init 里的 exit 不留结果标记，被主进程算成超时。Phase 2 用 *.err 通配，会把 Phase 1 的 _aws.err 也算进去，导致提前结束等待。超时后不先结束 worker 就删除临时目录，还在跑的 worker 写不回状态。
— 现象 — 批量结果里出现大量“装配异常/超时”，要等满 300 秒；报告的成功数可能比实际少。失败的实例还在计费，只能自己翻 logs/init_worker_<alias>.log 找原因。
— 修复方向 — worker 用 trap EXIT 无条件写入带原因的结果标记；Phase 1 和 Phase 2 用不同的扩展名；超时后先结束 worker 再清理；最后列出失败的实例并给出清理指引。
— 位置 — `core/init.sh:312`、`core/init.sh:406`、`core/init_aws.sh:662`、`core/init_aws.sh:675`、`core/init_aws.sh:702-707`
— 合并自 — BATCH-9

**A07 — init-aws 遇到同名的现有 Lightsail 实例会直接“接管”，并覆盖它整个云防火墙**

— 属性 — medium · AWS 自动部署 · AWS 路径 · 工作量 S
— 问题 — aws.py create 发现同名实例时不报错，直接拿来用，还用 put_instance_public_ports 覆盖它的全部端口规则。init-aws 防重名只靠在 ~/.ssh/config 主文件里 grep，如果别名写在 Include 文件里或者已经被删过，就查不出来。
— 现象 — 如果一台正在跑业务的实例碰巧叫 sg_aws-lightsail-1 之类的名字，init-aws 会报“实例创建成功”，实际上已经关掉了它的 80/8080 等端口，并把它改造成了节点；TG 的就绪看板也会把它列成新实例。
— 修复方向 — create 遇到已存在的实例默认报错，必须显式加 --adopt 才接管，接管时用 open_instance_public_ports 只增加放行；init-aws 调用前用 ssh -G 和 Lightsail API 两边查重。
— 位置 — `providers/aws.py:95-110`、`providers/aws.py:153-189`、`core/init_aws.sh:350-364`、`core/init_aws.sh:494`
— 合并自 — GAP1-5

**A08 — destroy-aws 区域写错或通配过宽时，会误删本地 SSH 条目、DNS 记录，甚至别的服务器**

— 属性 — medium · AWS 自动部署 · AWS 路径 · 工作量 M
— 问题 — 即使一台实例都没匹配上，destroy-aws 也会删除 ~/.ssh/config 条目和 Cloudflare 记录。清理孤儿记录本是有意设计，但它分不清“实例确实不存在”和“区域写错了”。通配删除既不预览也不确认，还会释放静态 IP。
— 现象 — 区域写错时，实例照常运行计费，本地 SSH 条目和伪装域名却被删了；加固过的节点，随机端口和影子用户只记在 config 里，删了基本就登不上了。`"sg*"` 这种过宽的通配，会把同前缀的其他项目实例连同静态 IP 一起不可逆地删掉。
— 修复方向 — 只清理 aws.py 实际删掉的实例对应的条目，没匹配到就什么都不删；删除前打印清单，要求确认或加 --yes；只删带 cnsr 标签的实例。
— 位置 — `core/destroy_aws.sh:104`、`core/destroy_aws.sh:116`、`core/destroy_aws.sh:139`、`core/destroy_aws.sh:174`
— 合并自 — BATCH-7

**C01 — 网关触发扫描返回 204 时，Worker 可能抛异常，init 误以为失败而重复派发扫描（未完全确认）**

— 属性 — medium · 扫描与网关 · 本地共用 · 工作量 S
— 问题 — GitHub dispatch 成功时返回 204，Worker 用 `new Response(await resp.text(), {status: 204})` 把它包一层；按 Fetch 规范，给 204 带 body 会抛异常，于是返回错误。init 因此判定网关失败，再用 GH_TOKEN 或 gh 重复派发一次。这个结论还没在真实的 Worker 环境里验证过。
— 现象 — 每次部署实际触发 2–3 次 Actions 扫描（12 台批量部署约 24–36 次），浪费配额。本地没有 GH_TOKEN 和 gh 时，还会误报“无法通过 Gateway / GH_TOKEN / gh 触发云端扫描”。
— 修复方向 — Worker 对 101/204/205/304 返回 `new Response(null, {status})`；init 收到网关的非 2xx 时先确认是否已经派发过，或者干脆统一由 reality_rotate --init 带时间戳派发。
— 位置 — `gateway/worker.js:75`、`core/init.sh:447`、`core/init.sh:455`、`core/init.sh:476`
— 合并自 — INIT-13

**H04 — 即使不加 --harden，部署也会重置整台主机的 UFW 防火墙**

— 属性 — medium · 加固 · 本地共用 · 工作量 M
— 问题 — 不管有没有 --harden，module_init 都会默认调用 apply_host_firewall（模板里 HOST_FIREWALL 默认就是 ufw）：先 `ufw --force reset`，再默认拒绝所有入站、只放行 22/443，所有输出和失败都被吞掉。这和“AWS 有云安全组就不需要主机加固”的思路正好相反：--harden 只管 SSH，主机防火墙却由另一个默认打开的开关控制，参数设计本身就是割裂的。新建的 AWS 实例上这基本无害，但在跑着其他服务的 VPS 上会直接把那些服务掐断。
— 现象 — 在已有其他项目的主机（如 sg-aws）上部署后，80/8080/3000 等非 Docker 服务立刻无法从公网访问，Let's Encrypt HTTP-01 续期悄悄失败。原来用 ufw-docker 限制过的 Docker 端口，在下次 ufw 重载后会暴露到公网。日志里看不到任何提示，也不知道备份在哪。
— 修复方向 — 不再 reset：UFW 已启用时只追加需要的规则，未启用时默认不启用（AWS 路径交给云防火墙）；打印并检查 ufw 的输出和返回值，在 README 里写明会对宿主机做哪些改动。
— 位置 — `lib/security.sh:43-104`、`core/init.sh:582-585`
— 合并自 — GAP1-2

**H05 — root 登录的 VPS 加固后，部署目录没迁过去，xray 和自愈都起不来**

— 属性 — medium · 加固 · 通用 VPS 路径 · 工作量 S
— 问题 — 加固迁移 Docker 目录时，按 /home/$CURRENT_USER 计算旧路径，可 root 的文件实际在 /root/docker-apps/xray，所以什么都没迁。调用方随后却无条件改用影子用户的目录。
— 现象 — 修好 V01 后，对 RackNerd 等 root 登录的 VPS 执行 `init <alias> <IP> --harden`：sshd 已经加固，但 xray 没启动，没有 cron，也没有 async_deploy。单机模式在“启动 X-ray 服务...”之后没有任何提示就退出，批量模式则把它标记为成功。
— 修复方向 — 迁移时用远端真实的 $HOME（或者由本地传入 REMOTE_HOME）计算旧路径，迁移后确认新目录里有 compose.yml，没有就返回失败。
— 位置 — `lib/security.sh:237-248`
— 合并自 — INIT-6

**H06 — Ubuntu 22.10 及以上（包括 Lightsail 的 Ubuntu 24.04）加固后，SSH 新端口不生效，节点失联**

— 属性 — medium · 加固 · 本地共用 · 工作量 S
— 问题 — 这些系统用 ssh.socket 做套接字激活，只改 sshd_config 里的 Port 再重启 sshd，并不会换监听端口，而 UFW 已经把 22 关了。没有云防火墙的 VPS 可以从厂商面板重启来恢复，Lightsail 上还会和 H01 的问题叠在一起。
— 现象 — 新端口 connection refused，22 端口被 UFW 丢包，网页 SSH 也用不了。
— 修复方向 — 先检测 ssh.socket 是否启用；启用的话 daemon-reload 后重启 ssh.socket（或改用 ssh.service），重启后用 ss -ltn 确认新端口在监听，再进入验证和切断流程。
— 位置 — `lib/security.sh:196-201`、`lib/security.sh:258-264`、`core/init.sh:504-510`
— 合并自 — HARD-4

**I01 — 对加固过的节点执行 rotate-ip，会抹掉本地记录的 SSH 端口，节点从此连不上，换 IP 半途中断**

— 属性 — medium · IP 与域名轮换 · AWS 路径 · 工作量 S
— 问题 — rotate-ip 调用 ensure_ssh_alias 更新 HostName 时没传端口，函数就把别名里的 Port 删掉了，之后所有 ssh 都连向 22；级联的 rotate-dns 已经在 Cloudflare 换好新子域、删掉旧 A 记录，却在下发服务器配置这一步被 set -e 中止。由于 H01、H03 让工具无法在 Lightsail 上产出可用的加固节点，目前只有操作者手动救回过的加固节点才会碰到，所以从 high 调为 medium；如果按重新设计在 AWS 路径上取消加固，它只剩下“ensure_ssh_alias 默认会删 Port”这个通用缺陷。
— 现象 — rotate-ip 打印“正在将新域名下发至服务器配置中”后报 `ssh: connect to host <新IP> port 22: Connection refused`，进程退出；Cloudflare 已换成新子域，节点仍用旧域名，之后 update、check、print 全部连不上。
— 修复方向 — rotate-ip 读取并传入现有的 Port 和 IdentityFile，并让 ensure_ssh_alias 在调用方没有显式传端口时保留原值。
— 位置 — `core/rotate.sh:528-534`、`lib/ssh.sh:11`、`lib/ssh.sh:119-125`、`lib/security.sh:274`
— 合并自 — GAP3-1

**I02 — 伪装域名创建失败会被悄悄吞掉，错误提示文字甚至会被当成域名写进节点链接**

— 属性 — medium · IP 与域名轮换 · 本地共用 · 工作量 S
— 问题 — init 用 `local FULL_DOMAIN=$(generate_cf_domain ... | tail -n 1)` 取域名，local 和管道把失败的返回码都掩盖了。缺 CF 凭据时，check_cf_credentials 把错误提示打到 stdout，结果被当成域名渲染进 SERVER_HOST。AAAA 创建失败时函数整体返回失败，已经建好的 A 记录留在 Cloudflare 上，节点退回用裸 IP。
— 现象 — 批量或 nohup 场景下没配 CF 时，vless 链接里的主机名变成“缺少 CF_API_TOKEN 环境变量！”，客户端连不上，部署却显示成功。AAAA 失败的节点（如日志里的 jp_aws-lightsail-4）链接用的是裸 IP，以后换 IP 就得重新导入。
— 修复方向 — 拆成 `local FULL_DOMAIN; FULL_DOMAIN=$(...) || 处理失败`，错误输出改到 stderr，并校验结果是合法的 FQDN；AAAA 失败时降级为只有 IPv4、仍然返回域名，或者回滚刚建好的 A 记录。
— 位置 — `core/init.sh:426-427`、`core/rotate.sh:33-60`、`core/rotate.sh:248-266`、`core/update.sh:129-141`
— 合并自 — INIT-9、XCUT-9、RUN-14、BATCH-8

**I03 — 生成伪装域名前，会删掉 Cloudflare 里所有指向本机 IP 的记录，不管是谁的**

— 属性 — medium · IP 与域名轮换 · 本地共用 · 工作量 M
— 问题 — init 和 rotate-dns 清理“历史冗余记录”时，按 content=本机 IP 或 comment=别名来匹配，不看记录名，同一个 Zone 里其他项目指向这台主机的业务域名和根域名都会被删。而且删除发生在创建新记录之前。
— 现象 — 在共享主机（如 sg-aws）上执行一次 init 或 rotate-dns 后，其他项目的网站立刻解析失败。终端只有一行“正在清理当前服务器历史冗余解析记录”，看不出到底删了什么。
— 修复方向 — 只删名字符合伪装前缀格式、并带本工具专用标记（如 comment=cnsr:<alias>）的记录；删除前打印清单；先建好新记录，再删旧记录。
— 位置 — `core/rotate.sh:117-144`、`core/rotate.sh:197-213`、`core/init.sh:426`、`core/rotate.sh:403`
— 合并自 — GAP1-4

**I04 — rotate-dns 先删旧域名再改服务器：中途失败或者全部成功，现有客户端都会断线**

— 属性 — medium · IP 与域名轮换 · 本地共用 · 工作量 M
— 问题 — rotate-dns 的顺序是先在 Cloudflare 删旧记录、建新记录，再 ssh 去改服务器。服务器那一步失败时被 set -e 中止，节点就一直用着已经删掉的旧域名，update、print、rotate-sni 还会把这个失效域名继续往外传。即使全部成功，也不推送新链接，提示里说“下一次 cron 将自动使用新域名”，和 cron 的实际行为对不上。
— 现象 — 执行 rotate-dns 后约 5 分钟（TTL 到期）内，所有客户端解析失败，TG 收不到新链接，只能手动 print，或者执行会作废全部凭据的 rotate-sni。如果是中途失败，除了再成功跑一次 rotate-dns，没有别的命令能修好。
— 修复方向 — 改成“先建新记录，再更新节点并严格校验，推送新链接，最后过一段宽限期再删旧记录”；任何一步失败都说明当前处于哪个中间状态，并能回滚。
— 位置 — `core/rotate.sh:403-444`、`core/rotate.sh:117-158`
— 合并自 — GAP3-2、GAP3-4

**I05 — 节点 SSH 不通或查不到公网 IP 时执行 rotate-dns，会把 A 记录全部删光**

— 属性 — medium · IP 与域名轮换 · 本地共用 · 工作量 S
— 问题 — rotate-dns 先通过 SSH 在节点上查询公网 IPv4（ifconfig.me、ipify），查不到时回退到 SSH 配置里的 HostName，而 DNS 收敛完成后 HostName 就是伪装域名本身。旧 A 记录先被删掉，再拿域名当 A 记录的内容去创建，必然失败。最容易触发的场景恰恰是节点被封、操作者 SSH 连不上时去换域名；SSH 正常时探测能拿到真实 IP，不会出问题。
— 现象 — 终端只显示“Cloudflare DNS A 记录创建失败”，但旧 A 记录已经被删掉，只用 IPv4 的客户端在 TTL 过后全部连不上。
— 修复方向 — IPv4 只接受通过格式校验的节点探测结果，拿不到时在任何 DELETE 之前中止，generate_cf_domain 入口也校验 IP 格式。
— 位置 — `core/rotate.sh:389`、`core/rotate.sh:396-400`、`core/rotate.sh:129-144`、`core/rotate.sh:152-195`
— 合并自 — GAP3-3

**I06 — 总是发布 IPv6（AAAA）记录，但所有检测只测 IPv4，IPv6 入站出了问题看不到**

— 属性 — medium · IP 与域名轮换 · 本地共用 · 工作量 M
— 问题 — init 和 rotate-dns 只要网卡上有 IPv6 地址就发布 AAAA，不验证 IPv6 入站到底通不通（云防火墙、容器、xray 监听都没检查）。而自愈、体检和 cnsr check 都只测 IPv4 或回环。
— 现象 — IPv6 优先的移动网络用户连不上，或者每条连接都要多等约 250–300ms，体检却显示正常，cron 判断“无需更换”。运维会以为是 SNI 被封，手动 rotate-sni、rotate-ip 都不见好转。
— 修复方向 — 只在 IP_STACK=dual 且 IPv6 入站验证可达时才发布 AAAA；回环探测、端口检查和体检都加上 IPv6 路径。
— 位置 — `core/init.sh:414`、`core/init.sh:426`、`core/rotate.sh:197`、`core/rotate.sh:389`、`lib/ssh.sh:251`
— 合并自 — GAP2-1

**I07 — rotate-ip 靠别名猜区域和实例名，猜错就失败，还留下一个计费的静态 IP**

— 属性 — medium · IP 与域名轮换 · AWS 路径 · 工作量 M
— 问题 — rotate-ip 从别名前缀推断区域（us_* 被映射成 us-east-1，和 us 模板里的 us-west-2 不一致），还要求 SSH 别名必须等于 Lightsail 实例名；aws.py 里按当前 IP 查找实例的分支从 CLI 根本走不到。它又是“先分配静态 IP、再 attach”，attach 失败不回滚。同样的“按别名猜地域”也用在选备用 SNI 池上，而同步下发的 fallback_snis.txt 从来没被读取过。
— 现象 — 美国节点或名字对不上的节点 IP 被封后，执行 rotate-ip 每次都只得到“静态 IP 换绑失败”。对应区域里却不断堆积没绑定（但在计费）的 ip-auto-xxxx 静态 IP，最后配额耗尽，连其他节点也换不了 IP。
— 修复方向 — 创建实例时把区域和实例名记到本地状态里（或者遍历各区域按 IP 定位实例），先确认实例存在再分配静态 IP，分配后任何一步失败都要释放回滚；reality_rotate 优先读 fallback_snis.txt。
— 位置 — `providers/aws.py:283-334`、`providers/aws.py:424-426`、`core/rotate.sh:473-480`、`core/rotate.sh:499`、`templates/us_aws-lightsail.conf:5`、`core/update.sh:215-217`
— 合并自 — BATCH-10、GAP3-7、XCUT-15

**I08 — 每换一次 IP 就长期占一个静态 IP 配额，同一区域换满 5 次后 rotate-ip 全部失效，而且看不到报错**

— 属性 — medium · IP 与域名轮换 · AWS 路径 · 工作量 M
— 问题 — 换 IP 的做法是“新分配一个静态 IP 挂上，再释放旧的”，所以每台换过 IP 的实例都会一直占着一个静态 IP，而 Lightsail 默认每个区域只有 5 个。aws.py 的 stderr 被 2>/dev/null 吞掉了。release 失败时 IP 其实已经换了，却被报告为失败。
— 现象 — 批量节点被封后执行 rotate-ip，接连收到原因不明的“换绑失败”。或者 IP 实际已经换了，本地却显示失败，节点从此失联，再重试一次又换掉一个 IP。
— 修复方向 — 改成不长期占用配额的方案（例如挂上新静态 IP 后立刻 detach 并 release，换取一个新的动态 IP，需要实测确认）；保留并展示 aws.py 的错误输出；release 失败时仍返回 new_ip 并给出警告；换 IP 前先检查配额。
— 位置 — `providers/aws.py:316-326`、`core/rotate.sh:499`、`core/rotate.sh:510-517`
— 合并自 — GAP3-6

**I09 — rotate-ip 只换 IPv4，IPv6 地址不变，还被原样发布到新域名上**

— 属性 — medium · IP 与域名轮换 · AWS 路径 · 工作量 M
— 问题 — Lightsail 的静态 IP 不包含 IPv6，换 IP 后实例的 IPv6 不变，级联的 rotate-dns 又把这个 IPv6 写进新子域的 AAAA。所谓“断臂求生”只换掉了一半身份，而且新域名和新 IPv4 可以通过这个 IPv6 被关联回旧身份。
— 现象 — 终端和 TG 都提示“自动换 IP 与自愈修复全部完成”，但 IPv6 优先的客户端还在走旧地址。旧 IPv6 被黑洞时，每条连接多等约 250–300ms；不支持 Happy Eyeballs 的客户端直接连不上。
— 修复方向 — 换 IP 时一并处理 IPv6（例如先切成 ipv4 再切回 dualstack 来拿新 IPv6，需要实测），或者新域名暂时不发布 AAAA；清理 AAAA 时按 comment==alias 无条件执行。
— 位置 — `providers/aws.py:316-334`、`core/rotate.sh:390-403`、`core/rotate.sh:197-265`、`core/update.sh:115-126`
— 合并自 — GAP3-5、GAP2-5

**L05 — Telegram 告警发不出去时，自愈会在换 SNI 之前直接中止**

— 属性 — medium · 自愈运行机制 · 节点端 · 工作量 S
— 问题 — SNI 被判定失效后，脚本先直接调用告警函数，再触发扫描。推送一失败就返回非零，`set -e` 立刻退出，扫描和换 SNI 都不会执行；网关模式下节点也没有直连 TG 的凭据可以兜底。瞬时失败（429、网络抖动）只会推迟一轮，但持续性的配置错误（Worker 没配 TG secrets 返回 500、AUTH_KEY 不一致返回 401）会让轮换永远不发生，而且所有节点都在 */15 整点触发，更容易撞上 429。
— 现象 — SNI 坏了却不轮换，rotate.log 停在“正在向 GitHub 发送扫描指令”附近；告警本身也没发出来，用户完全不知道。表现为“部署时正常，之后的自动轮换不工作”。
— 修复方向 — 所有通知调用都改成失败不致命（只记日志，下次补发），先完成扫描和轮换再发通知，并给各节点的 cron 加随机分钟偏移。
— 位置 — `templates/reality_rotate.template.sh:6`、`templates/reality_rotate.template.sh:47-99`、`templates/reality_rotate.template.sh:359-365`、`templates/reality_rotate.template.sh:599-601`
— 合并自 — DET-3、RUN-3、XCUT-4

**L06 — Xray 容器挂了或者根本没起来时，自愈既不修也不告警，还报“无需更换”**

— 属性 — medium · 自愈运行机制 · 节点端 · 工作量 M
— 问题 — 部署时 `docker compose up -d` 的失败被 `|| true` 吞掉，而自愈第 0 步发现容器异常时只会 restart，从不 up。restart 本身失败会被 set -e 静默中止；restart 没效果时，日志写“将继续全面轮换”，却没设置 FORCE_ROTATE，只要 dest 站点健康就以 0 退出，轮换后容器起不来也不会回滚旧配置。在共享主机上，如果 443 被别人占用或已有同名 xray 容器，探针还会把别人的容器和端口当成自己的。
— 现象 — 节点代理已经完全不可用（容器反复崩溃、停在 Created 或者根本不存在），rotate.log 每 15 分钟却都是“无需更换”，或者只有一行“尝试原生重启自愈”。用户最多收到一次告警，之后再无动静。
— 修复方向 — 自愈改用 `docker compose up -d`，并按本项目容器的 ID 判断是否存活；restart/up 失败或端口仍未监听时，设置 FORCE_ROTATE 或持续告警；写新配置前先备份，启动失败就回滚。
— 位置 — `templates/reality_rotate.template.sh:235-260`、`templates/reality_rotate.template.sh:291-294`、`templates/reality_rotate.template.sh:526-530`、`core/init.sh:576-577`、`templates/compose.yml.template:4-8`
— 合并自 — DET-7、RUN-9、GAP1-3

**L07 — 节点首轮部署（阶段二）意外失败时，既不告警也不清理**

— 属性 — medium · 自愈运行机制 · 节点端 · 工作量 S
— 问题 — async_deploy 在 `set -e` 下运行 reality_rotate --init。遇到 docker 不存在、缺 jq 这类意外时直接退出，既不发 TG，也不留下能看懂的失败记录；它自己只在等扫描 CSV 超时时才告警。
— 现象 — 部署后一直等不到节点配置推送，TG 上什么都没有，本地日志在“正在部署异步守护进程”之后就没有下文了。
— 修复方向 — 改成 `if ! ./reality_rotate.sh --force --init; then` 显式捕获失败，推送一条附带日志末尾几行的失败告警；或者用 trap ERR/EXIT 统一上报。
— 位置 — `templates/async_deploy.template.sh:5`、`templates/async_deploy.template.sh:129-140`
— 合并自 — INIT-12

**L08 — 节点每 15 分钟从 GitHub main 拉最新的自愈脚本，和 update 下发的版本互相覆盖，也不校验完整性**

— 属性 — medium · 自愈运行机制 · 节点端 · 工作量 M
— 问题 — runner 自更新不固定版本、不校验哈希或签名，直接拿 main 分支上的模板。所以本地修好并通过 update 下发的 reality_rotate.sh，15 分钟内就会被 main 上的版本覆盖回去，还可能和同时下发的 tg_templates.sh、reality_check.sh 版本对不上。这也意味着谁能写 main，谁就能在所有节点上以 sudo 能力执行代码，而非网关模式下节点自己就持有能写仓库的 GH_TOKEN。
— 现象 — “我修好并 update 了，rotate-sni 测试也正常，但 cron 自动轮换还是老样子。”
— 修复方向 — 自更新改为拉取 update 时记录下的固定 commit 或 tag，并校验 sha256；或者默认关闭从 main 自更新，只接受 cnsr update 推送；节点 .env 在远端 chmod 600。
— 位置 — `templates/runner.template.sh:21-27`、`gateway/worker.js:82-94`、`core/update.sh:161-174`、`core/update.sh:190`
— 合并自 — RUN-13

**R01 — 扫描没结果时换上的备用 SNI 全是热门大站，入选门槛还比扫描结果低**

— 属性 — medium · 选优与轮换 · 节点端 · 工作量 M
— 问题 — 备用池是一组热门 CDN 大站（例如 Apple 系域名），和 AWS 节点的 IP 明显对不上，却绕过了扫描路径的星级、CDN、热门、只收 200 等过滤，门槛更低。区域池按别名里的子串来选，可能选错（例如 msgnode 被匹配到 sg 池）。扫描一旦为空就直接跳到这些大站，备用池很容易变成实际的主路径。
— 现象 — 换到备用域名后伪装效果差，节点可能很快又失效，表现为“轮换了也没用”。
— 修复方向 — 备用候选走和扫描路径相同的过滤，或者改用预先审核过的同 ASN、同区域清单；扫描为空时先重试或适当放宽条件；区域按实例元数据判断，而不是看别名。
— 位置 — `templates/reality_rotate.template.sh:385-411`、`templates/reality_rotate.template.sh:489-501`、`templates/reality_rotate.template.sh:449`
— 合并自 — SEL-5

**S04 — 本机回环探测只要失败一次，就跳过三级防误判，直接整套轮换**

— 属性 — medium · SNI 失效检测 · 节点端 · 工作量 S
— 问题 — 回环探测（用当前 SNI 连 127.0.0.1:443）只试一次，失败就设置 FORCE_ROTATE，完全绕开了为外部检测设计的 3 次复核。会触发它的是传输层故障：xray 连 dest 被拒或被重置、TLS 握手失败、xray/docker-proxy 瞬间不可用，容器刚自愈重启后的那一轮尤其容易中招。curl 只设了连接超时、没有总超时，dest 握手后不回应时脚本会一直挂着。
— 现象 — 节点和 SNI 都好好的，却偶尔被整套换掉凭据（客户端跟着失效），同时还收到一条“SNI 被阻断”的误报。每个节点每天检测 96 次，偶发的概率会被放大。
— 修复方向 — 回环失败只记一次失败，和外部检测一起走跨周期的多次复核；容器重启后等就绪再测；curl 加上 --max-time 和重试。
— 位置 — `templates/reality_rotate.template.sh:238-266`
— 合并自 — DET-8、SEL-6、RUN-11

**S05 — DNS 投毒检测不可靠：没有应答被当成“被污染”，真被污染的反而判成干净**

— 属性 — medium · SNI 失效检测 · 节点端 · 工作量 M
— 问题 — 境内 DNS 查询没有应答时，按“已投毒”处理（fail-closed）；选用的 202.96.128.86、218.2.2.2 基本不回应境外来的查询，实际只靠 114。判断依据是一张过时的固定伪造 IP 表，识别不了 GFW 现在用真实境外 IP 做的伪造应答。候选预筛只查一次，偶尔丢个包就会把合格候选剔掉，把选择推向备用池。
— 现象 — 节点到境内 UDP/53 不稳定时，当前 SNI 会被误判失效，扫描结果整批作废，落到备用池。反过来，真正被污染的域名却可能被选成新 SNI。
— 修复方向 — 把“没有应答”（未知）和“检测到投毒”分开，未知不算失败；改用不依赖固定表的判定方法（例如向不提供 DNS 服务的境内 IP 发查询，只要有应答就是注入）。
— 位置 — `templates/reality_rotate.template.sh:154-184`、`templates/reality_rotate.template.sh:205-208`、`templates/reality_rotate.template.sh:463-473`
— 合并自 — SEL-2、DET-9

**S06 — 把 dest 网站的 HTTP 状态码当成 SNI 是否可用的依据**

— 属性 — medium · SNI 失效检测 · 节点端 · 工作量 S
— 问题 — 当前 SNI 的存活判断和扫描候选的筛选都看 dest 站点返回的 HTTP 状态码（扫描路径只收 200），而 REALITY 实际只依赖对方的 TLS 1.3/X25519/H2 和证书。dest 网站短时间返回 5xx 或被限流，和节点是否被封毫无关系。
— 现象 — dest 站点一抖动就误触发轮换；本来合格的扫描候选被丢掉，更容易落到备用池。
— 修复方向 — 存活判断只看 TLS 层指标，状态码只用于排序加权；扫描路径接受 checker 认为安全的状态码集合（200/301/302/404）。
— 位置 — `templates/reality_rotate.template.sh:219-220`、`templates/reality_rotate.template.sh:449`
— 合并自 — SEL-7

**V03 — jq、dig、cron、ufw 等依赖可能没装上也没人知道，自愈要么静默停摆，要么乱轮换**

— 属性 — medium · 通用 VPS 部署 · 本地共用 · 工作量 M
— 问题 — --harden 分支跳过了 cloud-init 和 dpkg 锁等待，依赖只装一次，失败还被 `|| true` 吞掉；非 apt 系发行版在普通分支上也装不上。装完不检查，reality-checker 也只有 x86-64 版本。缺 jq 时，reality_rotate 在定义告警函数之前就退出了；缺 dig 或跑在 ARM 上时，所有 SNI 都会被判死。
— 现象 — 加固节点的 rotate.log 每 15 分钟只有一句“系统未安装 jq”然后退出，从不自愈，也不告警。或者节点每 15 分钟重新生成一次全套凭据，TG 被“节点配置换新”刷屏。加固节点上的 ufw 和 fail2ban 实际上也没生效。
— 修复方向 — 把“等待 cloud-init 和锁 + 带重试安装”抽成两个分支共用的公共步骤，装完断言 jq、dig、crontab、docker（加固时再加 ufw、fail2ban）都存在，否则让部署失败；checker 按 uname -m 下发对应架构的版本。
— 位置 — `lib/security.sh:156`、`core/init.sh:504-548`、`templates/reality_rotate.template.sh:41-45`、`templates/async_deploy.template.sh:35`
— 合并自 — INIT-8、HARD-9、XCUT-12、RUN-10

**V04 — 用 root 登录、没装 sudo 的精简 Debian VPS 上，部署和加固全部失败**

— 属性 — medium · 通用 VPS 部署 · 通用 VPS 路径 · 工作量 M
— 问题 — 所有远端步骤都无条件加了 sudo，而 RackNerd 这类 root + 密码的 Debian 模板通常没有预装 sudo。docker、xray、cron 因此都装不上，批量或回退流程却仍然报告成功。
— 现象 — 部署“完成”后节点上什么都没有，既收不到配置，也没有告警。
— 修复方向 — 第一次远端操作时判断 `id -u`：root 下把 SUDO 设为空，缺 sudo 时先用 root 装上；所有远端脚本和模板统一使用 $SUDO。
— 位置 — `core/init.sh:519`、`core/init.sh:557`、`core/init.sh:569`、`core/init.sh:577`
— 合并自 — INIT-11

**V05 — Docker 安装失败时没有兜底，节点上没有 docker 却报告部署成功**

— 属性 — medium · 通用 VPS 部署 · 本地共用 · 工作量 M
— 问题 — get.docker.com 是用 `curl | sh` 管道执行的，下载失败会被掩盖；回退时装的 apt 包 docker-compose-v2 在 Debian 上根本不存在；`timeout 90` 还可能在 dpkg 运行到一半时把它杀掉。装完也不验证 `docker compose version`。
— 现象 — get.docker.com 或 download.docker.com 短暂连不上时，节点上就没有 docker，xray 永远不会启动，阶段一却仍然报成功。之后自愈在 restart 那一步静默退出，用户收不到任何告警。
— 修复方向 — 先把安装脚本下载成文件，校验后再执行；按发行版选正确的包名或使用 Docker 官方 apt 源；用 apt 的 DPkg::Lock::Timeout 代替 timeout；装完验证，失败就让流程失败。
— 位置 — `core/init.sh:557`、`core/init.sh:563-564`、`core/init.sh:577`
— 合并自 — INIT-5

**V06 — 在非 AWS 主机或启用了 IMDSv2 的主机上，同步脚本会把错误页当成公网 IP 写进节点**

— 属性 — medium · 通用 VPS 部署 · 本地共用 · 工作量 S
— 问题 — sync_node_scripts 用不带 -f 的 curl 读 169.254.169.254 的元数据，返回 HTTP 错误时 curl 照样成功，错误正文或空值就被当成 IP 或家目录，后面的公网兜底也不会执行。Lightsail 的 Ubuntu 24 / AL2023 镜像默认启用 IMDSv2，GCP、Azure、OCI、Linode 等厂商也各有不同的元数据格式。
— 现象 — 执行一次 check、update 或 rotate-sni 后，节点的 TARGET_IP 变成空值或“404 page not found”，CIDR 变成“none”。云端扫描要么被跳过，要么扫了无效目标，SNI 轮换拿不到新候选。
— 修复方向 — 元数据请求改走 IMDSv2（先 PUT 拿 token）并加 `curl -fs`；结果用 IPv4 正则和公网范围校验，不合格就继续兜底；不是 init 的调用，探测失败时保留已有的 TARGET_IP。
— 位置 — `core/update.sh:72-74`、`core/update.sh:87`
— 合并自 — INIT-7

**V07 — init 自己另写了一套 ~/.ssh/config 修改逻辑：会改错别的节点、丢条目，自定义配置路径时整条流程都连不上**

— 属性 — medium · 通用 VPS 部署 · 本地共用 · 工作量 M
— 问题 — module_init 没用 lib/ssh.sh 里的 ensure_ssh_alias，而是自己用 `cat >>` 和一段 Python 改写 ~/.ssh/config。它匹配 Host 块的正则用 \b 做边界，会把 jp_aws-lightsail 匹配到 jp_aws-lightsail-1；写的是写死的 ~/.ssh/config 而不是 SSH_CONFIG_PATH，后续 ssh 也不带 -F。写入时不加锁，和其他加了锁的写入方同时运行时会丢 Host 块。
— 现象 — 重跑 `init jp_aws-lightsail <新IP>` 后，jp_aws-lightsail-1 的条目被改成了新 IP，那台从此连不上。并发批量部署时，偶尔某个节点报“免密安全接管失败”，或者部署后 config 里少了条目。设置了 SSH_CONFIG_PATH 时报“Could not resolve hostname”，加固后的新端口和新用户也用不上。
— 修复方向 — 删掉 module_init 里自己写的 config 修改代码，统一走 ensure_ssh_alias（按 token 精确匹配、使用 SSH_CONFIG_PATH、加 flock）；所有 ssh/scp 统一带 -F，或者改成每个节点一个 Include 文件。
— 位置 — `core/init.sh:325-371`、`core/init.sh:403`、`lib/ssh.sh:36`、`lib/ssh.sh:324`、`lib/security.sh:284`
— 合并自 — INIT-10、BATCH-15、BATCH-16、HARD-12

**V08 — 工作区里未提交的 compose 改动（开 IPv6 但不指定子网），在旧版 Docker 上会让容器起不来**

— 属性 — medium · 通用 VPS 部署 · 节点端 · 工作量 S
— 问题 — 当前未提交的 compose.yml.template 改动给默认网络加了 enable_ipv6，却没指定 subnet。Docker 27.0.1 之前不会自动分配 IPv6 子网，网络直接创建失败，而 compose up 的失败又被吞掉了。在 ip6tables 关闭或宿主没有 IPv6 的机器上，原来的“立即失败”会变成“黑洞超时”；在新装 Docker（≥27）的双栈 Lightsail 上，它大概率能修好 V02，但没有任何检测来确认。
— 现象 — 在已经装了旧版 Docker 的 VPS 上部署，容器根本起不来，终端却提示阶段一完成，之后既没有配置推送也没有告警。在没有 IPv6 的宿主上，访问双栈站点从偶尔失败变成偶尔长时间卡住。
— 修复方向 — 显式配置 IPv6 子网；部署前检测 Docker 版本、ip6tables 和宿主的 IPv6 默认路由，不满足就退回纯 IPv4 网络，并配合 V02 改成 IPv4 策略。
— 位置 — `templates/compose.yml.template:18`、`core/init.sh:554`、`core/init.sh:577`、`core/init.sh:498`
— 合并自 — GAP2-4

**A09 — 模板里的安全参数大多是摆设，--region 覆盖后还会沿用原区域的密钥**

— 属性 — low · AWS 自动部署 · AWS 路径 · 工作量 M
— 问题 — SECURITY_PROFILE、PROVIDER 基本没被代码用到，IP_STACK 只影响 UFW 的 IPv6 开关，不影响实例的 IP 类型和 AAAA 发布；--harden 又是一个独立的命令行开关，和模板里的安全策略毫无关联。这正是“AWS 靠云安全组、不需要加固；VPS 只有 root 密码、需要加固”这种区分在参数层面表达不出来的原因之一。另外，--region 只覆盖 REGION，模板里按区域生效的 KEY/ZONE 仍会被沿用。
— 现象 — 用模板加 --region 部署到别的区域时，所有实例都创建失败（再叠加 A03 就是无限转圈）；改了 SECURITY_PROFILE 或 IP_STACK 也看不到任何效果。
— 修复方向 — 实现或删掉这些假选项，把“是否加固、由谁管防火墙”做成由部署路径决定的统一参数；--region 覆盖时如果 KEY/ZONE 对不上就报错，创建前用 get_key_pair 预检密钥。
— 位置 — `core/init_aws.sh:781-816`、`templates/jp_aws-lightsail.conf:10-19`
— 合并自 — BATCH-13

**A10 — 用模板执行 destroy-aws，找不到默认只建一台时创建的那台实例**

— 属性 — low · AWS 自动部署 · AWS 路径 · 工作量 S
— 问题 — `destroy-aws -f <模板>` 的匹配模式固定是 `${ALIAS}-*`，而 COUNT=1 时创建的实例名就是 ${ALIAS} 本身，不带序号。
— 现象 — 提示“未找到匹配的实例”，实例、SSH 条目和 DNS 记录都还在，一直计费。
— 修复方向 — 模板模式下同时匹配 `${ALIAS}` 和 `${ALIAS}-[0-9]*`，或者按创建时打的标签删除；删除前列出匹配结果。
— 位置 — `core/destroy_aws.sh:55`、`core/init_aws.sh:780`、`core/init_aws.sh:353`
— 合并自 — BATCH-11

**A11 — 查询 AWS 实例状态连续失败时 aws.py 崩溃，真正的错误原因被吞掉**

— 属性 — low · AWS 自动部署 · AWS 路径 · 工作量 S
— 问题 — create_instance 轮询 get_instance，20 次都抛异常时（例如 IAM 不允许 lightsail:GetInstance、持续断网或被限流），变量 inst 没有被赋值，于是抛出 UnboundLocalError，而真实的 AWS 异常早已被 except 吞掉。不管有没有这个问题，该节点都会被判为创建失败，影响只在于诊断信息。
— 现象 — 日志里只有一个 Python UnboundLocalError，看不出到底是权限问题还是网络问题。
— 修复方向 — 循环前先初始化 inst，并保存最后一次异常，超时后输出结构化的错误 JSON。
— 位置 — `providers/aws.py:155-166`
— 合并自 — CX-6

**C02 — 扫描结果没有请求编号，新节点可能用上旧网段的数据，每次初始化还要扫两遍**

— 属性 — low · 扫描与网关 · 节点端 · 工作量 M
— 问题 — init 派发的扫描不带时间戳，async_deploy 只看通用的 `${alias}.csv` 是否返回 200，而同名别名的旧数据在 KV 里会保留 30 天，“等首轮扫描”可能被直接跳过；随后 reality_rotate --init 又派发第二次扫描。带时间戳的扫描 240 秒内没出结果时，会回退到 `${alias}.csv`，却不校验它是不是当前网段的数据。rotate-ip 级联 rotate-sni 时最容易碰到这种情况，而且还会误发一条“SNI 被阻断”的告警。
— 现象 — 新节点或刚换 IP 的节点，选出的 SNI 来自旧网段，或者因为排队超时落到备用池；Actions 运行次数翻倍；换 IP 后还会先收到一条误导性的 SNI 阻断告警。
— 修复方向 — 全链路用同一个请求时间戳（init 生成，async_deploy 精确等待，并传给 reality_rotate --init 复用，不再重复派发）；回退时校验 CSV 的来源网段和当前 TARGET_CIDR 一致；手动或强制轮换不发阻断告警。
— 位置 — `core/init.sh:429-453`、`templates/async_deploy.template.sh:90-127`、`templates/reality_rotate.template.sh:351-379`、`gateway/worker.js:97-126`、`core/rotate.sh:302`
— 合并自 — RUN-15、XCUT-11、SCAN-6、SEL-9、GAP3-9

**C03 — IPv6 网段扫描在 GitHub 托管的 runner 上永远扫不出结果**

— 属性 — low · 扫描与网关 · 节点端 · 工作量 S
— 问题 — 扫描任务会对节点所在的 IPv6 /112 做邻居扫描，但 GitHub 托管的 runner 没有 IPv6 出口，IPv6 候选永远是空的。节点一定有 IPv4，IPv4 /22 的结果足够用，所以影响主要是“双栈扫描”名不副实。
— 现象 — 宣称的双栈扫描对 IPv6 不起作用，白白占用扫描时间。
— 修复方向 — 在没有 IPv6 出口的 runner 上明确跳过 IPv6 目标，或者改用有 IPv6 的 self-hosted runner。
— 位置 — `core/init.sh:417`、`core/update.sh:121`、`.github/workflows/scan.yml:84`、`.github/workflows/scan.yml:90`
— 合并自 — SCAN-5

**H07 — fail2ban 防爆破形同虚设：还在守已经弃用的 22 端口，Debian 12 上可能根本没在运行**

— 属性 — low · 加固 · 本地共用 · 工作量 S
— 问题 — sshd jail 没有跟着换到随机的新端口，仍然守着 22。Debian 12 默认没有 auth.log，jail 很可能起不来，失败又被 `|| true` 吞掉了。
— 现象 — 帮助文案说“启用高强度系统加固与防爆破防火墙”，实际起不到防爆破的作用。
— 修复方向 — 写入 jail.d/cnsr-sshd.local，指定新端口和 backend=systemd，确保装了 python3-systemd，最后用 `fail2ban-client status sshd` 验证。
— 位置 — `lib/security.sh:156`、`lib/security.sh:191`
— 合并自 — HARD-8

**H08 — IP_STACK=ipv4 时，IPv6 入站反而完全不设防**

— 属性 — low · 加固 · 本地共用 · 工作量 S
— 问题 — IP_STACK=ipv4 时，UFW 被设成 IPV6=no，ip6tables 完全没人管，主机的 IPv6 入站全部开放。
— 现象 — 用户以为“只用 IPv4”更收敛，实际上在没有云防火墙的通用 VPS 上，SSH 等端口在 IPv6 上完全裸露。
— 修复方向 — 保持 IPV6=yes，对 IPv6 同样默认拒绝入站；确实只要 IPv4 时，用 sysctl 关掉 IPv6，或者显式写入 IPv6 全部拒绝的规则。
— 位置 — `lib/security.sh:77-81`
— 合并自 — HARD-10

**H09 — 加固只改主 sshd_config，可能被 sshd_config.d 里的配置覆盖而不生效**

— 属性 — low · 加固 · 本地共用 · 工作量 S
— 问题 — 加固直接用 sed 改主文件里的 PasswordAuthentication、PermitRootLogin，而 sshd_config.d 里的 drop-in 会覆盖这些值，sshd -t 也查不出来。由于同时写入的 AllowUsers 只允许没有密码的影子用户，root 实际上仍然登不上，风险主要是配置漂移，以及对外暴露了密码认证方式。
— 现象 — 界面显示加固完成，但 `sshd -T` 里密码认证仍然是开着的。
— 修复方向 — 改为写一个字典序最靠前的 drop-in（例如 /etc/ssh/sshd_config.d/00-cnsr-harden.conf），写完用 `sshd -T` 校验实际生效的值，不符合就回滚。
— 位置 — `lib/security.sh:203-215`、`lib/security.sh:226-234`
— 合并自 — HARD-5

**H10 — Docker 发布的端口绕过 UFW，PORTS_TCP/PORTS_UDP 白名单管不到 Xray 实际对外的端口**

— 属性 — low · 加固 · 本地共用 · 工作量 M
— 问题 — Docker 会直接改 iptables，容器发布的端口不受 UFW 规则约束。
— 现象 — 按模板调整 PORTS_* 想收紧端口，不会生效；以后 compose 如果再加端口，即使 UFW 显示 deny，也照样对公网开放。
— 修复方向 — 在 DOCKER-USER 链（写进 /etc/ufw/after.rules）里按白名单约束，或者采用 ufw-docker 方案；在文档里说明 PORTS_* 对容器端口的作用范围。
— 位置 — `templates/compose.yml.template:6-8`、`lib/security.sh:86-100`、`core/init.sh:576-585`
— 合并自 — HARD-11

**H11 — 加固后，原用户名下留着一条指向已迁走目录的失效 cron，加固和主机防火墙两个步骤还互相冲突**

— 属性 — low · 加固 · 本地共用 · 工作量 S
— 问题 — 把部署目录迁到影子用户名下时，不清理原用户的 runner cron，它每 15 分钟报一次错，还会产生本地邮件。之后 apply_host_firewall 按 PORTS_TCP 的默认值又把 22 放行了（sshd 已经不监听 22，没有安全影响），和加固的意图不一致。
— 现象 — 加固节点上不断出现 cron 报错，本地邮件越积越多；防火墙最终状态和预期不符。
— 修复方向 — 迁移目录时清理原用户的 cnsr cron 条目；加固模式下 apply_host_firewall 从 PORTS_TCP 里去掉 22，或者把两处防火墙逻辑合并；把影子用户和端口持久化，方便重跑时复用。
— 位置 — `core/update.sh:242`、`lib/security.sh:236-256`、`core/init.sh:506-508`、`core/init.sh:584`
— 合并自 — HARD-13

**I10 — 伪装子域名可能和别的节点撞名，导致约一半连接打到错误的节点上**

— 属性 — low · IP 与域名轮换 · 本地共用 · 工作量 S
— 问题 — 子域名只从大约 5400 个候选里随机挑，生成后不检查 Zone 里是否已经有同名记录。撞名时，两个节点的 A 记录同时存在，DNS 轮流解析到两边。
— 现象 — 偶尔出现“某个节点时好时坏、大约一半连接失败”，看起来很像 SNI 或 REALITY 失效，很难定位。
— 修复方向 — 生成后检查已有记录，撞名就重新生成，并扩大随机空间。
— 位置 — `core/rotate.sh:73-75`、`core/rotate.sh:155`
— 合并自 — BATCH-14

**I11 — 域名收敛时不核对解析出来的 IP，可能把别名绑到另一台节点上**

— 属性 — low · IP 与域名轮换 · 本地共用 · 工作量 S
— 问题 — DNS 收敛 worker 收到了 expected_ip 却从不比对，只要“能解析出结果 + 能 SSH 登录”，就把 HostName 升级成域名，还删掉该域名的 known_hosts 记录。和 I10 的子域撞名叠加时，别名可能指向另一台节点。
— 现象 — 概率不高：别名 X 的连接在两台节点之间来回跳，间歇性出现“REMOTE HOST IDENTIFICATION HAS CHANGED”。如果第一次就连到了节点 Y，update 或 rotate-sni 会以 X 的身份覆盖 Y 的脚本，并在 Y 上轮换。
— 修复方向 — 要求解析结果包含 expected_ip 且只有一条 A 记录；ssh 探测时用 HostKeyAlias 和已知的主机公钥比对；升级时迁移公钥，而不是删除。
— 位置 — `lib/ssh.sh:270-311`、`lib/ssh.sh:361-395`、`core/rotate.sh:437`
— 合并自 — GAP3-8

**L09 — 安装 cron 时会顺手删掉同一用户下其他项目里含 runner.sh 的定时任务**

— 属性 — low · 自愈运行机制 · 本地共用 · 工作量 S
— 问题 — 重装 cron 时用 `grep -v -E 'reality_rotate.sh|runner.sh'` 过滤旧条目，这个正则太宽，路径里带 runner.sh 的其他任务都会被删。init、update、check、rotate-sni、test 在同步文件时都会重写 crontab。
— 现象 — 在共享主机上执行 init、update 或 rotate-sni 后，其他项目的备份、CI runner 等定时任务悄悄消失，没有任何提示。
— 修复方向 — 给自己的条目加唯一标记（例如行尾加 `# cnsr:<alias>`），只增删带这个标记的行。
— 位置 — `core/init.sh:579`、`core/update.sh:242`、`core/rotate.sh:302`
— 合并自 — RUN-12

**R02 — 轮换生成的新凭据不做校验，也不做真实连接验收，坏配置会直接上线**

— 属性 — low · 选优与轮换 · 节点端 · 工作量 M
— 问题 — 新的 UUID 和密钥靠固定的输出标签解析出来，从不检查是否为空。UUID 命令在管道里，`|| exec` 这个降级分支被 tr 的退出码 0 屏蔽成了死代码，compose run 失败而 exec 能用时会拿到空 UUID；写入后的验收只测回环 TLS，不覆盖 REALITY 认证，客户端用推送的 UUID/pbk/sid 实际连不上时系统发现不了。触发条件比较窄：镜像版本是固定的，空私钥只会在 xray x25519 的输出格式变化时出现。
— 现象 — 一旦触发，所有客户端都会失效，而之后 cron 的回环检测仍显示正常，不自愈也不告警，直到有人手动 rotate-sni。
— 修复方向 — 写入前校验所有凭据非空且格式正确，并备份旧配置；轮换后用 xray 客户端模式、按新凭据对 127.0.0.1:443 做一次真实的 VLESS+REALITY 请求，失败就回滚。
— 位置 — `templates/reality_rotate.template.sh:523-530`、`templates/reality_rotate.template.sh:547-560`、`templates/reality_rotate.template.sh:570-580`、`templates/reality_rotate.template.sh:251-260`
— 合并自 — CX-7、DET-12

**R03 — 扫描找到的“同网段邻居”这个属性，在选 SNI 时被丢掉了**

— 属性 — low · 选优与轮换 · 节点端 · 工作量 M
— 问题 — 选优时丢掉了 CSV 里的 IP 列，dest 用域名重新解析，而不是用扫描到的邻居 IP，也不校验候选是不是真的和节点在同一个 /22 或 ASN；扫描路径用的还是重定向后的最终域名。它对实际失效的影响只是推测。
— 现象 — 选出来的 SNI 和节点 IP 不在同一个网络，邻居扫描失去了意义；还可能选中别人代理节点的域名，跟着它一起被处置。
— 修复方向 — 保留 IP 列，优先选解析结果落在节点 /22 或同 ASN 的候选，并排除节点自身和已知兄弟节点的 IP。
— 位置 — `templates/reality_rotate.template.sh:418`、`templates/reality_rotate.template.sh:476-482`、`templates/reality_rotate.template.sh:551`、`.github/workflows/scan.yml:90`
— 合并自 — SEL-8

**R04 — 健康检查验证的是重定向后的域名，写进 dest 的却是重定向前的原名**

— 属性 — low · 选优与轮换 · 节点端 · 工作量 S
— 问题 — check_sni_health 实际检测的是 dest 重定向之后的最终域名，但备用池和当前 SNI 写进 dest 的是原名，这个原名本身从来没被验证过是否支持 TLS1.3/X25519。
— 现象 — REALITY 握手可能失败，健康检查却一直显示正常。
— 修复方向 — 从 checker 输出里解析出最终域名，作为 NEW_SNI 和 dest；或者直接对原名用 openssl s_client 验证 TLS1.3/X25519/H2。
— 位置 — `templates/reality_rotate.template.sh:211-226`、`templates/reality_rotate.template.sh:280`、`templates/reality_rotate.template.sh:491-498`
— 合并自 — SEL-11

**R05 — 候选 SNI 的解析和过滤有几处细节错误**

— 属性 — low · 选优与轮换 · 节点端 · 工作量 S
— 问题 — 排除当前 SNI 用的是正则子串匹配，CURRENT_SNI 为空时会把所有候选都清掉；通配符证书被转成了根域名；CSV 的列号是写死的；jq 失败时在 set -e 下静默退出。
— 现象 — 在一些极端配置下，候选被清空，或者排除了错误的域名，自愈脚本静默退出。
— 修复方向 — 排除改用 `grep -vxF`，CURRENT_SNI 为空时跳过；按表头名定位列；通配符改为加 www. 前缀或直接丢弃；jq 失败时告警，并用模板重建配置。
— 位置 — `templates/reality_rotate.template.sh:151`、`templates/reality_rotate.template.sh:418`、`templates/reality_rotate.template.sh:453`
— 合并自 — SEL-12

**R06 — 选 SNI 时，OCSP 装订的权重压过了星级和握手延迟**

— 属性 — low · 选优与轮换 · 节点端 · 工作量 S
— 问题 — 排序时 OCSP 装订排在星级前面（延迟只通过星级间接起作用），而对 Let's Encrypt 证书来说 OCSP 已经没有意义；逐个预筛也让候选一多时轮换耗时明显变长。影响轻微。
— 现象 — 选中的不一定是星级最高、延迟最低的候选；候选多时轮换明显变慢。
— 修复方向 — 以星级、握手延迟、是否同网段作为主要排序依据，OCSP 只在打平时用来裁决；预筛前先截取前 N 个候选并发执行。
— 位置 — `templates/reality_rotate.template.sh:186-195`、`templates/reality_rotate.template.sh:457-482`
— 合并自 — SEL-13

**R07 — test-sni 和 rotate-sni --dry-run 并不是空跑，会真的删缓存、触发扫描、发告警**

— 属性 — low · 选优与轮换 · 节点端 · 工作量 S
— 问题 — 帮助里写的是“空转预演模式：只嗅探高分域名，不修改配置”，但 DRY_RUN 下仍会删除节点上的 CSV、真实派发 GitHub 扫描、推送 SNI 阻断告警，还会启动容器生成密钥。
— 现象 — 每演练一次都会消耗一次 Actions 配额，清掉节点缓存的扫描结果，还产生告警噪音。
— 修复方向 — DRY_RUN 下跳过删 CSV、推送告警、派发扫描和生成密钥，只用现有的 CSV 或备用池做评估。
— 位置 — `core/rotate.sh:269-339`、`core/test.sh:102-114`、`templates/reality_rotate.template.sh:264-266`、`templates/reality_rotate.template.sh:352-379`
— 合并自 — XCUT-14

**S07 — 体检把 443 没监听、容器反复重启的节点判成“正常”**

— 属性 — low · SNI 失效检测 · 节点端 · 工作量 S
— 问题 — reality_check 下结论时只看部分指标，忽略了 443 没监听和容器处于 restarting 状态，也没把回环穿透的结果算进去。批量 init 的 --notify-on-error 因此会把真实的故障静默掉。
— 现象 — 批量部署后 Xray 其实没起来，体检却显示“节点健康检查正常，静默跳过推送”。
— 修复方向 — 容器状态不是 running 或端口没监听时判为红色，并把回环穿透结果纳入结论。
— 位置 — `templates/reality_check.template.sh:353-370`、`templates/reality_check.template.sh:391-401`、`templates/reality_check.template.sh:444-446`
— 合并自 — DET-10

**S08 — cnsr check 的本地握手探针不可靠，结论和处置建议都可能是错的**

— 属性 — low · SNI 失效检测 · 本地共用 · 工作量 S
— 问题 — 拿不到公网 IP 时，会回退到 AWS 私网 IP 去探测。探测从操作者本机发出，开着代理时结果会受代理路径影响。判定为 BLOCKED 时一律建议换 SNI，不区分 TCP 不通（应该换 IP）和 TLS 被重置。
— 现象 — 偶尔误报“假死”，开代理时又可能漏报；即使结论对了，给出的处置建议也可能是错的。
— 修复方向 — 复用会拒绝私网地址的 IP 探测逻辑，给 openssl 加超时并检测本机代理，同时探测 v4 和 v6，按失败类型分别建议 rotate-ip 或 rotate-sni。
— 位置 — `core/check.sh:46-55`、`core/check.sh:62-89`、`core/check.sh:110-122`
— 合并自 — DET-11

**S09 — TG 体检报告里的“Reality 公钥”一栏永远是空的**

— 属性 — low · SNI 失效检测 · 节点端 · 工作量 S
— 问题 — tpl_health_full 漏掉了第 23 个参数，公钥字段因此一直是空的。
— 现象 — 没法用体检报告核对客户端里配置的公钥。
— 修复方向 — 补上 `local pub_masked="${23}"`，并为模板的参数位置加单元测试。
— 位置 — `templates/tg_templates.sh:172-173`、`templates/tg_templates.sh:241`、`templates/tg_templates.sh:283`、`templates/reality_check.template.sh:449-450`
— 合并自 — DET-13

**T01 — 测试全绿也说明不了部署和自愈可用：入口、编排和自愈主流程从没被真正执行过**

— 属性 — low · 测试 · 本地共用 · 工作量 L
— 问题 — 测试不经过 cnsr.sh 入口，不覆盖 init/init-aws 的编排顺序，也不覆盖 reality_rotate/reality_check 的主流程；部分用例是同义反复，不在 set -e 下运行，mock 也不带 spec。所以 V01、A01、H01、L01、S03 这类入口参数、执行顺序和错误语义上的缺陷，都能通过 CI。
— 现象 — CI 一直是绿的，但部署和自愈实际上是坏的。
— 修复方向 — 增加经 cnsr.sh 入口的端到端打桩测试（mock ssh 按 -F/-p/User 模拟可达性，并能注入失败）；为两个节点脚本写场景测试；所有测试在 set -e 下运行；CI 引入 shellcheck。
— 位置 — `tests/test_core_operations.py:38-44`、`tests/run_tests.sh:7-21`、`tests/test_templates.py:355-388`、`tests/test_lib_security.py:206-240`
— 合并自 — XCUT-13

**T02 — 跑测试会改写仓库里真实的 .env，测试中途被杀掉时，真实凭据会被 mock 值覆盖**

— 属性 — low · 测试 · 本地共用 · 工作量 S
— 问题 — 部分测试直接读写仓库根目录的 .env，还依赖里面的真实 AWS 凭据。测试不会把凭据发到外部，但进程中途被杀掉时，真实的值会丢失。
— 现象 — 跑完测试发现本地 .env 里的 AWS 凭据变成了 mock 值；测试结果也会随开发者本机 .env 的状态而变。
— 修复方向 — 测试在临时目录里复制一份仓库，或者通过环境变量指定 .env 路径，绝不碰仓库根目录的 .env。
— 位置 — `tests/test_core_operations.py:403-433`、`tests/test_core_operations.py:660-697`、`tests/test_core_operations.py:713-718`、`tests/test_cnsr_sync.py:231`
— 合并自 — XCUT-16

**V09 — init 把 SSH 端口写死成 22：非 22 端口的 VPS 会被误报“密钥被拒”，甚至被防火墙锁在门外**

— 属性 — low · 通用 VPS 部署 · 通用 VPS 路径 · 工作量 M
— 问题 — 普通 init 没有 --port 参数，也不探测 sshd 实际监听的端口：带 IP 时用 22 探活，失败后把端口问题误诊成密钥问题。如果沿用别名里的非 22 端口，或者本地 `Host *` 设了 Port，apply_host_firewall 会把 UFW 重置成只放行 22/443，把真正的 SSH 端口封掉。目前被 V01 挡住了，修好 V01 后就会出现。
— 现象 — 对 2222 等端口的 VPS 执行 init，约 24–48 秒后提示“免密探测失败：目标服务器拒绝了该密钥认证”。或者部署进行到一半，scp 超时，此后再也登不上 SSH，只能去控制台救援。
— 修复方向 — init 增加 --port；在远端用 `sshd -T` 拿到实际监听的端口并一起放行；改完防火墙先用新连接验证能连上；探活失败时区分“连接被拒/超时”和“认证失败”。
— 位置 — `core/init.sh:297`、`core/init.sh:307`、`core/init.sh:371-380`、`core/init.sh:502`
— 合并自 — GAP1-1

**V10 — 等 apt 锁超过 60 秒就强杀 dpkg 并删除锁文件，可能弄坏主机的软件包状态**

— 属性 — low · 通用 VPS 部署 · 本地共用 · 工作量 S
— 问题 — 普通分支在 dpkg 锁被占用 60 秒后，执行 `killall -9 apt-get apt unattended-upgrades dpkg` 并删除锁文件，再 `dpkg --configure -a || true` 接着部署。常见后果是软件包停在半配置状态，或者依赖装不上。
— 现象 — init 恰好赶上系统自动更新或别人在用 apt 时，其他项目之后的 apt 会报“dpkg was interrupted”，正在升级的服务停在半升级状态。新实例上也可能因此没装上 jq 等依赖（见 V03）。
— 修复方向 — 改用 `apt-get -o DPkg::Lock::Timeout=600` 排队等待，绝不 kill dpkg、不删锁文件，等超时就明确失败，并输出是哪个进程占着锁。
— 位置 — `core/init.sh:525-546`
— 合并自 — GAP1-6

**V11 — 用 root 初始密码登录的交互模式，公钥明明注入成功了，仍然报“密钥被拒”**

— 属性 — low · 通用 VPS 部署 · 通用 VPS 路径 · 工作量 S
— 问题 — 密码登录模式把 ~/.ssh/pub/<alias>.pub 写成 IdentityFile，并设置了 IdentitiesOnly。如果私钥不在 ssh-agent 里，探活时就拿不到对应的私钥。
— 现象 — 通用 VPS 走交互式密码登录，密码输对了、公钥也注入了，仍然报“免密探测失败：目标服务器拒绝了该密钥认证”并退出；写进 config 的 IdentityFile 之后也用不了。
— 修复方向 — 本地有对应私钥时，把 IdentityFile 指向私钥；只有 agent 里确实持有这把 key 时才用 .pub；ssh-copy-id 失败时明确报错。
— 位置 — `core/init.sh:265`、`core/init.sh:272`、`core/init.sh:285`、`core/init.sh:291`
— 合并自 — INIT-14

**V12 — 改了 compose 模板后重跑 init 或 update，节点上的 compose.yml 不会更新**

— 属性 — low · 通用 VPS 部署 · 本地共用 · 工作量 S
— 问题 — compose.yml 只在远端不存在时才下发，不在 update 的哈希同步范围内（config.json 也一样）。
— 现象 — 本地和远端的 compose 配置不一致（例如旧的日志策略、没有 IPv6 网络），排查时容易被误导；V02、V08 的修复也没法通过 update 下发到已部署的节点。
— 修复方向 — 把 compose.yml 纳入哈希差异同步，内容变化时执行 `docker compose up -d` 重建容器；config.json 因为含密钥，仍然只在缺失时写入，另外提供单独的迁移命令。
— 位置 — `core/init.sh:498`、`core/update.sh:205`
— 合并自 — INIT-16

**V13 — 部署对主机做的全局改动没有边界，也没有任何卸载办法**

— 属性 — low · 通用 VPS 部署 · 本地共用 · 工作量 M
— 问题 — 部署会写 /etc/sysctl.d/99-reality.conf，覆盖 qdisc 和拥塞控制设置，还会重置 UFW、写 cron，项目却没有卸载路径。reality_check 还会按通配符删除 /tmp/ping_*（受粘滞位限制，只影响同一用户的文件）。
— 现象 — 停用 cnsr 后，共享主机上的内核网络参数、防火墙和定时任务都不会恢复，runner 继续每 15 分钟跑一次。
— 修复方向 — sysctl 改用优先级更低的文件名，或者只在没有设置过时才写入；提供 `cnsr uninstall <alias>`，负责删除 cron、容器、网络、sysctl 文件并恢复 UFW 备份。
— 位置 — `core/init.sh:568-579`、`core/update.sh:241-242`、`templates/reality_check.template.sh:122`
— 合并自 — GAP1-7

**V14 — 交互式 init 选完菜单后，按 Ctrl-C 无法中止部署**

— 属性 — low · 通用 VPS 部署 · 本地共用 · 工作量 S
— 问题 — select_menu 设置了全局的 INT/EXIT trap，而且之后从不恢复。
— 现象 — 在约 48 秒的探活循环或较长的远端安装过程中按 Ctrl-C 没有反应，用户以为程序卡死而强行关掉终端，留下一台装了一半的节点。
— 修复方向 — 函数开头保存原来的 trap，返回前恢复；或者只 trap RETURN，并在 INT 处理里恢复光标后 exit 130。
— 位置 — `lib/ui.sh:126`
— 合并自 — INIT-15

