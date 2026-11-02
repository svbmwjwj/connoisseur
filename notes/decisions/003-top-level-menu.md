---
id: D-003
created: 2026-10-28
updated: 2026-10-28
type: decide
source: user
status: active
supersedes:
doc: cli-menu-design.md
---

# 一级菜单只有部署、删除、列表

## 决定

不带参数运行 cnsr 时弹出一级菜单，只有三项：部署服务器、删除服务器、服务器列表。

## 备选

保留 add 作为一级命令，把功能选择放在 add 下面；或者只提供一级命令、不做菜单。

## 缘由

add 和 rm、list 搭配都不自然；部署、删除、列表三项各自独立，作为一级菜单更清楚。
