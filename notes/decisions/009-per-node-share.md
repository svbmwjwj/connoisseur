---
id: D-009
created: 2026-11-24
updated: 2026-11-24
type: decide
source: user
status: active
supersedes:
doc: cli-menu-design.md
---

# 单个节点可以不经过订阅直接添加

## 决定

`cnsr list <别名>` 显示这一台的圈X 配置行和 `vless://` 链接，可以直接导入软件，也可以单独分享给别人。订阅继续保留给自己的设备用。

## 备选

- 只提供订阅：拿到地址的人能看到全部节点，而且只有一个 token，不能单独作废。
- 给每个人单独的 token 或 UUID：可以按人收回，但要改控制端鉴权或节点配置，这次不做。

## 缘由

用户要能分享单个节点，而不是把整个订阅交出去。手动添加的节点不会跟随换 SNI，需要重新发。
