###### cnsr 计划一真机验证交接（任务 17，AWS 路径）

给新对话用的交接说明。计划一的代码（`cnsr add`、`cnsr rm`）已全部实现并通过审阅，这次只做 AWS 路径的真机验证。

**代码在哪**

— 分支 — `claude/project-overview-289241`，共 29 个提交，只在本地，没有推送。
— 工作区 — `~/Developer/snack-connoisseur/.claude/worktrees/project-overview-289241`。这个工作区来自工作区池，可能已被回收；如果被回收了，就在新工作区里检出上面这个分支。
— 测试现状 — `uv run pytest -q` 为 1419 passed，`uv run node --test tests/worker/*.test.mjs` 为 21 passed。
— 相关文档 — 设计：`.notes/cnsr-redesign-spec_zh-cn.md`；计划：`.notes/cnsr-impl-plan-deploy_zh-cn.md`（Task 17 一节）；进度账本：`.superpowers/sdd/cnsr-impl-plan-deploy_zh-cn/progress.md`。

**边界（必须遵守）**

— 只用临时实例 — 放在东京，名字以 `cnsr-test-` 开头，绑定已有的 `jp-key` key pair，测完立即删除实例和静态 IP。
— 不碰生产机 — 永远不碰新加坡的生产实例 `prod-sg`，也不碰 `prod-us` 上的 `xray` 容器、443 端口和 SSH 配置。
— 凭据由你输入 — Cloudflare token、域名和 AWS 凭据都由你在自己的终端里输入，助手不代为输入。
— 不推送 — 所有改动只在本地。

**步骤**

1. 准备：解锁 SSH agent，确认里面有 `jp-key`；暂停这台 Mac 上的圈X（扫描必须直连）。
2. 部署：在工作区目录运行 `uv run cnsr add cnsr-test-1 --aws jp`。选钥匙时选 `jp-key`。
3. 核对：实例在 `ap-northeast-1`，规格 `nano_3_0`，系统 Debian 13 或 12；防火墙只开 22/tcp、443/tcp、443/udp；`ssh cnsr-test-1` 能通过域名登录。
4. 客户端：把输出的两段配置粘贴到 iPhone 上的圈X，确认节点能用。
5. 重跑：再运行一次 `uv run cnsr add cnsr-test-1`，应该没有新实例，UUID 和 SNI 不变。
6. 删除：运行 `uv run cnsr rm cnsr-test-1`。实例、静态 IP、两条 DNS 记录、控制端里的这一行和 SSH 别名都应删掉。即使前面失败，也必须做这一步，不能留下计费资源。
7. 记录：把结果写回设计文档第 15 节。

控制端（Worker `cnsr-control`、同名 KV 和一个随机子域名）在 `rm` 之后会保留，这是设计如此。

**要顺带确认的事（代码里没法离线验证）**

— Cloudflare — KV 写入（multipart 格式）；token 的写权限检查是否准确；缺少读取域名权限时返回空列表还是 403；绑定 Workers 自定义域名需要哪项权限。
— 外部探测 — Worker 的 `connect()` 能否连到节点的 IPv6 字面量地址。
— 公共 DNS — 暂停圈X、直连时，`cloudflare-dns.com`、`1.1.1.1` 或阿里 DNS 至少有一个能查到记录。
— 钥匙 — Lightsail 显示的 ED25519 指纹格式（带 `=` 的 base64）能否让 `jp-key` 被直接复用，而不是重新导入。
— 开机 — 新实例从创建到能 SSH 登录要多久，期间有没有出现被归为“其他”的 SSH 错误。
— 体检 — Lightsail Debian 镜像上 `preflight.sh` 是否干净通过，镜像里有没有 curl。
— 写文件 — `install -m 600 /dev/stdin <路径>` 在 Debian 上是否可用。
— Docker — `install-docker.sh` 在 Debian 13（trixie）上能否装好。
— Xray — `xray run -test` 的参数写法；`config.json` 权限为 644 时容器能否读到；`127.0.0.1:443` 能否连到映射出来的容器端口。
— 握手自检 — `verify-reality.sh` 的客户端字段：Xray 26.3.27 认 `publicKey` 还是 `password`。如果被拒，改成 `password`。
— 候选验证 — 节点上的 curl 是否支持 `--curves X25519`。
— AWS 基线 — `sshd -T -C` 的核验能否通过。
— 扫描 — 从国内直连扫一个 /20 要多久，命中多少、最后剩几个候选；两个出口回显地址是否可用。
— 删除 — 解绑静态 IP 时，“未绑定”这种错误的原文措辞。

**已知的未修问题（只影响小厂商路径，这次不涉及）**

定时器刚触发、恢复脚本还在运行的那几秒内如果正好重跑，cnsr 可能误报“已经加固过”。这不会锁死服务器，下次重跑会补完，建议在测小厂商真机之前修掉。
