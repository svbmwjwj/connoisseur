---
id: D-013
created: 2026-11-24
updated: 2026-11-24
type: decide
source: user
status: active
supersedes:
doc: cli-menu-design.md
---

# 更换主用户分两步

## 决定

`cnsr user reset <别名>` 给主用户换新的 UUID，订阅随之更新，旧的保留成一个普通用户。设备都更新订阅后，再用 `cnsr user rm` 收回旧的。

## 备选

- 一步换掉：这台电脑可能正用旧 UUID 经过节点上网，换完立刻断线，没法确认结果。
- 换订阅地址的 token：针对订阅地址泄露，所有设备都要换新地址，是另一件事，这次不做。

## 缘由

主链接发给别人之后要能收回，同时不能把自己的设备和连接切断。
