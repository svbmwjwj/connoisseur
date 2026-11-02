---
id: D-006
created: 2026-10-28
updated: 2026-10-28
type: decide
source: user
status: active
supersedes:
doc: cli-menu-design.md
---

# 部署命令叫 up

## 决定

一级菜单“部署服务器”对应的命令是 `cnsr up [别名]`。

## 备选

`deploy`、`new`、`set`。

## 缘由

用户希望命令名更简单；`up` 和 `docker compose up` 的用法一致，新部署和对已有服务器重跑续部署都说得通。
