---
id: D-011
created: 2026-11-24
updated: 2026-11-24
type: decide
source: user
status: active
supersedes:
doc: cli-menu-design.md
---

# 节点可以添加用户，并单独收回

## 决定

给一台 Xray 节点添加用户：每个人一个单独的 UUID，可以单独收回，不影响其他人。只做添加和收回，不做按人看流量、限速和到期。

## 备选

- 所有人共用节点的主 UUID：无法只收回某一个人。
- 同时做按人看流量：要开 Xray 的统计接口并处理重启清零，工作量比添加用户大，以后需要再做。

## 缘由

分享单个节点之后，要能收回某一个人的使用权。订阅只用主 UUID，用户不进订阅。
