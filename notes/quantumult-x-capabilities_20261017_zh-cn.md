###### 圈X 客户端检测能力核实

4 路研究，每路配一个反驳者，来源以官方仓库 crossutility/Quantumult-X、示例脚本、官方频道存档和社区脚本原文为主，没有安装或运行圈X，也没有连接任何服务器。

**已确认**

— 指定节点或直连发请求 — `$task.fetch({ url, opts: { policy: "direct" } })`，policy 可以是 `direct`、策略组名或单个节点 tag。带 policy 的请求不复用连接，每次都完整握手，官方说明适合做检测。
— 调用内置测速 — `$configuration.sendMessage({ action: "url_latency_benchmark", content: [节点tag...] })`，返回 `{"ret": {"tag": [TCP握手ms, HTTP延迟ms]}}`，失败项为 -1。
— 失败的表现 — 网络层失败时 promise 被 reject，可读取 `reason.error`；HTTP 非 2xx 不算失败，走正常分支，用 `statusCode` 判断。
— 远程节点订阅 — 远程 snippet 可以原样写 VLESS REALITY Vision 行，只要 tag 仍是 `self-built`，现有 `resource-tag-regex=^self-built$` 的策略继续生效。
— cron 语法 — 支持 5 位或 6 位（第一位是秒）；`$task.fetch` 默认超时 10 秒；`$notify`、`$prefs`、`setTimeout` 都可用，脚本必须调用 `$done()`。
— 托管位置 — `*.workers.dev`、`*.vercel.app` 在国内基本不通。Cloudflare 免费套餐挂在自有域名上，国内通常能直连但延迟高，由境外机房服务；2025 年出现过部分 Cloudflare IP 被封的事件。raw.githubusercontent.com 时通时断。

**大概率成立（间接证据）**

— 后台运行 — 定时任务在圈X Tunnel（VPN）进程里执行，锁屏、不在前台也能跑，前提是 VPN 开着、并且“计划任务”开关打开。
— 内置测速做完整 REALITY 握手 — 所以 IP 被封时 TCP 那一项失败，SNI 或握手被阻断时 HTTP 那一项失败，两者可以区分。
— 订阅下载走规则 — 远程订阅由主程序下载，Tunnel 运行时按当前分流规则出站，没有参数能强制直连；可以在 `[filter_local]` 里加一条 `host, <订阅域名>, direct` 间接实现。
— 订阅何时更新 — 自动更新大概只在打开圈X 时触发，不会在后台定时拉取。脚本也无法触发订阅更新。

**未确认**

— 系统睡眠 — iPhone 锁屏进入系统睡眠后，定时任务会延后到下次唤醒；醒来后是补跑还是跳过，不清楚。
— macOS 版 — 是否和 iOS 一样在后台跑任务，没有一手资料；Mac 睡眠时肯定不跑。
— 订阅下载失败时是否保留旧节点 — 不清楚。
— 节点参数变化但 tag 不变时，策略里选中的节点是否保留 — 不清楚，大概率保留。
— `reason.error` 的具体文案 — 超时、重置、TLS 失败时分别返回什么字符串，不清楚。

**已知的误报来源**

— 后量子密钥交换 — 圈X 的 REALITY 使用带 X25519MLKEM768 的 iOS 26 Safari 指纹；如果服务端 Xray 较旧而伪装目标站支持 MLKEM，握手会失败，表现和被封一样。
— TFO — REALITY 不应开 TFO，ClientHello 超过 1500 字节，TFO 永远不会成功。
