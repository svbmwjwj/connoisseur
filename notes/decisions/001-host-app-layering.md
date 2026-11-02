---
id: D-001
created: 2026-10-27
updated: 2026-10-27
type: decide
source: user
status: active
supersedes:
doc: layering-design.md
---

# 分开服务器层与应用层

## 决定

在代码里把“开机器、接管、加固”这部分（服务器层）和“装 Xray”这部分（应用层）分开，让服务器层不再引用 Xray 的东西。先写设计文档，暂不改代码。

## 备选

- 维持现状：只做 Xray，两层继续混在一起。
- 扩展成通用的自定义镜像工具。

## 缘由

以后可能在节点上部署别的内容，分层之后服务器层可以直接复用。做成通用镜像工具会和 Packer、cloud-init 这些现成方案重复，cnsr 的定位也会变模糊，所以没有选。
