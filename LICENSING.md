# 许可与第三方组件

本仓库原创代码、脚本、补丁和文档采用 **GNU General Public License v2.0 or later（GPL-2.0-or-later）**，完整许可文本见 [LICENSE](LICENSE)。带有独立版权或许可声明的文件按其声明处理。

HomeProxy 及基于其原有代码产生的修改保留 **GPL-2.0-only** 约束；将补丁应用到 HomeProxy 后，生成文件按 HomeProxy 的许可分发。仓库的默认许可不会把第三方文件重新授权。

| 目录或组件 | 许可说明 |
| --- | --- |
| `upstream/homeproxy/`、HomeProxy 原始 IPK 和生成的 HomeProxy 覆盖文件 | 保留上游 GPL-2.0-only 与文件内版权声明 |
| sing-box 源码、原始/压缩挂载 IPK、Windows 工具 | 保留上游 GPL-3.0-or-later 与附加命名声明；详见源码 LICENSE |
| ucode 与 digest 模块 | 保留 ISC 许可 |
| squashfs-tools-ng 和附带库 | GPL、LGPL、BSD、MIT 等，按发行包与源码内许可分项处理 |
| ImmortalWrt 固件、SDK、ImageBuilder、工具链及 feeds | 多个组件的集合，保留各组件自己的许可；不统一改为本仓库默认许可 |
| QSDK 候选的上游 OpenWrt/Linux、驱动、固件归档和生成的 SDK/ImageBuilder | 保留各组件的上游许可与声明；来源和内容摘要见 `firmware/qsdk/source-lock.json`，固件归档的内容锁定不构成重新授权 |
| 历史候选 WebUBoot 二进制 | 作为历史归档保留上游权利与来源说明，不因本文件取得新的授权 |

第三方声明、许可文本和来源记录位于 `dependencies/licenses/`、`dependencies/lock.json`、各源码快照及官方发行包。Release 原样镜像上游构建产物，同时提供本仓库的对应公开源码快照、构建记录与校验表。

源码快照中的外部 Linux 源码包、Go 模块及其他构建下载仍需依固定配方补齐；Release 中的 SDK 不代表已归档所有传递构建输入，也不表示本项目已完成一次新的固件源码重编译。
