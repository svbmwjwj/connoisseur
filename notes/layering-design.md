---
created: 2026-10-27
updated: 2026-10-28
---

# cnsr 分层设计：服务器层与应用层

## 背景

cnsr 现在只做一件事：部署 Xray REALITY 节点，并在 SNI 失效时自动更换。以后可能会在节点上部署别的内容，所以先把“开机器、接管、加固”和“装 Xray”这两部分在代码里分开。

本文只写方案，不改代码。决定都标了来源，待定的项目列在文末。

## 目标与不做的事

- 目标：服务器层不再引用 Xray 的任何东西，以后换一种应用或加一种应用时，服务器层的代码和测试不用动（用户，D-001）。
- 定位不变：cnsr 仍然是节点工具，不扩展成通用的镜像工具或配置管理工具；这类需求交给 Packer、cloud-init、Ansible 这些现成工具（Claude）。
- 行为不变：拆分期间命令、提示、流水线的步骤和顺序、KV 里的记录格式都保持原样（Claude）。
- 不为假想场景预留：没有第二种应用之前，不设计插件机制，也不加配置项（Claude）。

## 现状

`src/cnsr` 共约 7600 行，按职责大致分成两层[^1]。

### 服务器层

- 云资源：`aws/`，负责 Lightsail 实例、静态 IP、防火墙。
- 登录：`ssh/`，负责密钥、agent、`~/.ssh/config` 别名、远程执行。
- 接管与加固：`server/preflight.py`、`server/harden.py`、`server/baseline.py`，以及 `assets/node/` 里对应的 `preflight.sh`、`harden-*.sh`、`baseline-check.sh`、`install-docker.sh`。
- 流水线骨架：`deploy/steps.py` 里的逐步执行、续跑、断线重试，以及 `deploy/steps_host.py`（第 1～3 步）、`deploy/reach.py`、`deploy/static_ip.py`。
- 域名：`deploy/dns_records.py`、`cloudflare/dns.py`，负责节点的 A/AAAA 记录。

### 应用层（Xray）

- 配置与部署：`server/xray.py`、`assets/xray/`、`deploy/steps_node.py`（第 6、7 步）。
- SNI：`scan/`、`deploy/steps_sni.py`（第 4、5 步）。
- 自动更换：`deploy/steps_rotate.py`（第 8 步），以及 `assets/node/` 里的 `cnsr-rotate.*`、`rotate-*.sh`、`validate-candidates.sh`、`verify-reality.sh`。
- 客户端：`qx.py`、`cloudflare/control.py`、`assets/worker/`、`assets/qx/`。

### 耦合点

- 接管标记：`deploy/steps_host.py:122` 和 `:128` 用 `/opt/cnsr` 判断这台机器是否已被接管，但这个常量是 `server/xray.py:24` 的 `NODE_DIR`。它表示“cnsr 接管过的机器”，属于服务器层。第一阶段已解决。
- 应用端口写在服务器层：`server/preflight.py:18` 和 `:81`～`:87` 检查 443；`aws/lightsail.py:42` 让防火墙放行 443/tcp 和 443/udp；`deploy/steps_host.py:298` 的提示里也写着 443。这三处都应该由应用层告诉服务器层“要开哪些端口”。第一阶段已解决。
- 节点记录：`state.py:62` 的 `Node.xray` 是 Xray 专用字段，`Node.line` 是客户端配置行。两者都是可选字段，KV 里存的 JSON 格式也依赖它们。
- 步骤列表：`deploy/steps.py:19` 的 `STEPS` 和 `TITLES` 把两层的 8 步写成一个固定的元组。
- 上下文：`deploy/context.py:81` 的 `Deps` 和 `:174` 的 `DeployContext` 同时装着两层的依赖和中间结果，比如 `hits`、`sni`、`rotation_stopped`。
- 小厂商防火墙：`assets/node/harden-stage.sh` 写死了 `ufw allow 443/tcp`、`443/udp`，第一阶段漏掉了；2026-10-28 在 `feat/up-menu` 上改成由 cnsr 传入端口（见 `cli-menu-design.md`）。
- `rm`：`commands/rm.py` 不登录服务器，只删云资源、DNS、别名和 KV 记录（其中含 SNI 更换状态），所以它对应用层的依赖只在 KV 记录这一处。

## 分层方案

### 服务器层的职责

服务器层只回答一个问题：一台机器有没有准备好，能不能交给应用。它负责下面几件事（Claude）：

- 地址：拿到机器的 IPv4/IPv6，必要时新开 Lightsail 实例或换静态 IP。
- 接管：第一次登录、预检、留下接管标记。
- 加固：SSH 改端口、禁止密码登录、开启自动安全更新，按应用给出的端口设置防火墙。
- 名字：写 SSH 别名和 DNS 记录。

### 应用层的职责

应用层拿到一台准备好的机器，负责装上自己的服务、维护自己的状态，并给出客户端要用的东西。Xray 应用就是现在的第 4～8 步（Claude）。

### 两层之间的接口

应用层向服务器层提供三样东西（Claude）：

- 端口：要放行的端口列表，比如 Xray 是 `(443, "tcp")` 和 `(443, "udp")`。预检用它判断端口是否被占用，Lightsail 防火墙和加固提示也用它。
- 步骤：应用自己的步骤函数和标题，接在服务器层的第 1～3 步后面。
- 记录：应用自己的字段在 `Node` 里怎么存、怎么读。

服务器层向应用层提供已经登录、加固好的 `Remote`、节点记录和 UI。应用层不直接调用 `aws/`，只有在需要换 IP 时通过 `deploy/reach.py` 的现有入口调用（Claude，待调研：Xray 步骤里哪些地方会触发换 IP，第二阶段动手前再核实）。

### 目录

第二阶段完成后的目录大致如下（Claude）：

- `src/cnsr/host/`：现在的 `aws/`、`ssh/`、`server/` 里除 `xray.py` 以外的部分、`deploy/steps_host.py`、`reach.py`、`static_ip.py`、`dns_records.py`。
- `src/cnsr/apps/xray/`：现在的 `server/xray.py`、`scan/`、`deploy/steps_node.py`、`steps_sni.py`、`steps_rotate.py`、`qx.py`。
- `src/cnsr/deploy/`：只保留流水线骨架，即 `steps.py` 和精简后的 `context.py`。
- `assets/`：`node/` 里属于应用的脚本挪到 `assets/xray/`，服务器层的脚本留在 `assets/node/`。

`cloudflare/` 两层都在用：DNS 属于服务器层，控制面和 Worker 属于 Xray 的客户端分发，所以第二阶段再决定它怎么拆（待定）。

## 实施阶段

### 第一阶段：零行为变化的小拆分

只处理接管标记和端口两处耦合，在分支 `refactor/split-host-layer` 上完成，源码 6 个文件、测试 5 个文件（用户，D-002；具体做法 Claude）：

- 接管标记：`NODE_DIR = "/opt/cnsr"` 移到 `server/preflight.py`，因为这个模块本来就负责判断能不能接管；`server/xray.py` 改为从那里引用，路径本身不变。
- 端口：Xray 的端口定义为 `server/xray.py` 的 `PORTS`；`preflight.evaluate` 和 `Lightsail.set_firewall` 都改成接收端口参数，22/tcp 仍由服务器层自己放行。
- 传递：`DeployContext` 新增必填字段 `app_ports`，由 `commands/add.py` 传入 `xray.PORTS`。`deploy/steps_host.py` 不能引用 `deploy/steps.py`（会循环导入），所以没有按原计划从 `steps.py` 传。
- 提示：加固后的提示改为按端口生成，文字仍是“Lightsail 防火墙只放行 22 和 443”。
- 验证：`uv run pytest` 1932 个、`uv run node --test tests/worker/*.test.mjs` 107 个全部通过，与改动前相同；测试只改了调用处，断言没改。

### 第二阶段：拆流水线和目录

- 步骤：`STEPS` 拆成服务器层 3 步加应用层步骤，标题和顺序不变，`RERUNNABLE_FROM` 的含义不变（Claude）。
- 上下文：`DeployContext` 拆出应用层自己的状态对象，`Deps` 按两层分组（Claude）。
- 记录：`Node` 的 JSON 字段名保持不变，已部署节点的 KV 记录不需要迁移（Claude）。
- 测试：`tests/cnsr/` 跟着目录拆开，测试文件按层归入子目录（Claude）。
- 时机：等出现第二种要部署的应用再做，那时按真实需求设计接口（Claude；是否提前做，待定）。

## 风险

- 续跑：第二阶段如果改了步骤编号或 KV 字段，正在使用中的节点重新 `add` 时可能找不到原来的进度。所以字段名和步骤顺序都不改。
- 测试替身：`tests/cnsr/*_fakes.py`、`*_harness.py` 依赖 `Deps` 现在的字段，拆分 `Deps` 时要同步改。第二阶段的工作量主要在这里。
- 范围蔓延：第二阶段很容易顺带重写其他代码。每次改动只做搬迁和接口调整，不改逻辑。

## 待定事项

- [x] 第一阶段什么时候做：2026-10-27 已做（D-002）。
- [ ] 第二阶段是等第二种应用出现再做，还是提前做。
- [ ] 第二种应用是什么，这决定接口的具体形状。
- [ ] `cloudflare/` 在两层之间怎么拆。

[^1]: 行数与模块划分来自 2026-10-27 在 `main`（`3f8c2b5`）上对 `src/cnsr` 的 `wc -l` 和 `from cnsr` 导入关系统计。
