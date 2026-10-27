# 固定上游源码

`homeproxy/` 来自 ImmortalWrt LuCI 的 `9b8ee6470c5eb1e5189f1a7f25bc8ee958e2a7c3`，路径为 `applications/luci-app-homeproxy/`。安装包版本为 `26.236.50592~9b8ee64`。这个版本号末尾指向 **LuCI feed 提交**，不能拿它当独立 `immortalwrt/homeproxy` 仓库的提交。

`recipes/sing-box/` 来自 packages feed `27a0f631a93f63bff9865526a9b4a74a10ca82f5`，对应源码版本 1.12.25；这是核对过的配方快照，不表示已确定官方 IPK 的所有原始构建输入。`recipes/ucode/` 来自当前固件源码提交，版本与 digest 模块一致。

本目录原样保留，不直接放本机凭据。当前定制逻辑在 `scripts/`，补丁构建使用归档 IPK 中真正交付的文件作为输入，避免压缩后的 JavaScript 与未压缩源码哈希混淆。源码文件清单由依赖锁校验，更新上游时需同步提交来源与文件哈希。
