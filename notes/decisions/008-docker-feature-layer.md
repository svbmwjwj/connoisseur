---
id: D-008
created: 2026-11-22
updated: 2026-11-22
type: decide
source: user
status: active
supersedes:
doc: cli-menu-design.md
---

# Docker 单独成为一层功能

## 决定

部署路径改为三层：基础加固 → Docker → Xray 节点，可以只部署到 Docker 为止，留给用户部署自己的 Docker 服务。只到 Docker 时，cnsr 不放行任何应用端口，端口由用户自己处理。

## 备选

- 维持现状：Docker 只在 Xray 的步骤里顺带安装，没法单独得到一台装好 Docker 的服务器。
- 让用户在部署时填写自己服务的端口，由 cnsr 一并放行。

## 缘由

用户要在加固好的服务器上部署自己的其他 Docker 服务。端口由各自的服务决定，用户选择自己管理，cnsr 不介入。
