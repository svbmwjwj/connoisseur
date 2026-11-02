---
id: D-007
created: 2026-10-28
updated: 2026-10-28
type: research
source: claude
status: active
supersedes:
doc: cli-menu-design.md
---

# 补装功能时在第 3 步补开端口

## 决定

已经由 cnsr 加固过的小厂商服务器，重跑 `cnsr up` 时第 3 步在补全加固之后，用 `ufw allow` 补开这次所选功能的端口。

## 备选

在 Xray 的部署步骤开头自己放行 443。

## 缘由

防火墙属于服务器层；AWS 那边第 3 步本来就每次按所选功能重设 Lightsail 防火墙，小厂商机器放在同一步，两种服务器的做法一致，Xray 层也不用碰防火墙。`ufw allow` 对已有规则不做改动，重复执行没有副作用。
