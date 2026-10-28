# CR8808 有线 NSS 候选固件

这是为普通 IPv4 NAT 持续不低于 500 Mbps、给现有 300–350 Mbps 宽带留出资源余量而准备的候选。**尚未通过本机固件启动、吞吐或长期稳定性验收。** 构建成功也不等于这些检查已经通过。

当前日常系统仍是已归档的 ImmortalWrt 24.10 / Linux 6.6.137。此前同网段 NAS 读取已达到约 924 Mbps；它走交换芯片，不是必须替换固件的原因。新候选的重点是降低普通路由/NAT 的 CPU 负担。

## 固定输入与策略

[source-lock.json](../firmware/nss/source-lock.json) 固定主树和全部六个 feeds。主树为 kuncy7/openwrt-nss-edma 的 `c36db6321c11595dc45a160cdab36b5c2d787744`；NSS feed 为 `57c0fa18f847f6cb23992ff3493c6a9131246f4c`。其余 feeds 与已核对的 2026-10-23 上游发行记录一致。

采用 CR8806/CR8808/CR8809 同硬件家族的 `xiaomi_cr8806` 配方。候选构建要求：

- 有线 NSS/ECM 启用；无线 NSS 编译支持保留，但运行时关闭，先使用主机无线处理路径。
- 256 MiB ath11k 配置、NSS LOW、DTS 中 8 MiB NSS 保留内存与 512 KiB coherent_pool。
- 从源码删除增加 1296 MHz 的设备树补丁，首次启动再设最高 1008 MHz。
- nft 软件分载和 nft 硬件分载开关均关闭，避免与这套 ECM/NSS 抢先处理流量；这不等于关闭 NSS。
- HomeProxy 与当前 sing-box 1.12.25 的已校验压缩镜像继续使用。功能缓存、GFWList/节点测速代码和日志下载 ACL 修复从现有维护基线重建。
- 新内核模块全部随 Linux 6.18 构建；不将现有 6.6 IPK 或 `.ko` 放入新镜像。
- 原厂物理系统槽为 36 MiB。factory 镜像限制为最多 32 MiB，为 UBI 元数据、可写空间和坏块留出物理空间；这不代表刷入后必有 4 MiB 可用 UBIFS 空间，仍须实机检查。

公开候选没有家庭 Wi-Fi 密码、代理节点、订阅、root 密码或设备分区。默认不会替用户恢复旧系统的无线配置。个人设置需要在设备迁移环节单独准备、核对后应用。

## 构建和产物

[Build wired NSS candidate](../.github/workflows/nss-candidate.yml) 在 `codex/nss-wired-candidate` 分支相关文件变化时运行；也可手动运行。工作流使用只读仓库权限，不发布 Release、不连接家庭路由器、不执行刷写。

流程先验证冻结依赖、测试迁移保护，再检出固定 NSS 源码，生成公开应用配方和 feeds，运行 `make defconfig` 并核对所有请求项没有被丢弃。feeds 的真实 Git HEAD 也必须逐个与锁文件一致。随后下载源码、编译完整固件和匹配 APK，并检查镜像、包清单、metadata 与大小，上传候选 artifact。

在已有依赖的 Linux 环境中，准备阶段的等价命令如下；这不是刷机命令：

```sh
git clone https://github.com/kuncy7/openwrt-nss-edma.git tmp/nss-source
git -C tmp/nss-source checkout c36db6321c11595dc45a160cdab36b5c2d787744
python scripts/prepare-nss-candidate.py --source tmp/nss-source --output tmp/nss-preparation
cd tmp/nss-source
./scripts/feeds update -a
./scripts/feeds install -a
make defconfig
python ../../scripts/prepare-nss-candidate.py --verify-config .config
make download -j2
make -j2
```

artifact 包含 factory UBI、sysupgrade、FIT initramfs、对应 manifest、构建配置、来源/准备/构建报告、SHA256、构建日志，以及保存匹配 `bin/targets` 和 `bin/packages` 的压缩包。失败构建也会保留已有配置和日志，不能将这种 artifact 当作完整镜像。

候选暂不启用随时间变化的官方 snapshot 包源。完整匹配 APK 与索引保存在 artifact 中；后续模块安装须使用同一内核构建对应的包。HomeProxy 的资源更新和订阅网络请求不依赖 APK 包源。

## 恢复与迁移边界

本机原厂槽位、当前 ImmortalWrt 槽位与备份应在实际写入前重新读取并校验。旧 `flash-cr8808-stock.template.sh` 针对“从原厂 rootfs 写入另一槽”的条件，**不适用于直接从当前系统套用这次 NSS 升级**。也不应以强制 sysupgrade 绕过 `redmi,ax3000` 与 `xiaomi,cr8806` 的设备标识差异。

下一阶段需要在本机私有目录准备当前配置、分区/启动环境与恢复校验记录，核对新旧引导标志和 UBI/ECC 要求，再给出针对实际状态的写入/恢复步骤。厂商同系列原厂固件可互刷，不代表新驱动、引导环境工具与所有插件已经组合验收。

新驱动生成的无线硬件路径可能与旧系统不同；不能将整个旧 `/etc/config/wireless` 无检查覆盖。应保留新系统生成的硬件路径，再迁移 SSID、密钥和频段设置。公开构建不会读取或打包这些个人信息。

## 设备验收

镜像就绪后，先核对具体 SHA256、恢复资料和断网窗口，再安排设备写入。运行时提供只读命令：

```sh
check-cr8808-nss
# 有测试流量时，额外要求 ECM 实际加速连接数大于零：
check-cr8808-nss --require-traffic
```

至少验证：

1. 实际槽位、启动、双频无线、WAN DHCP、LAN DHCP/DNS 与 NAS 访问。
2. 最高 CPU 频率不超过 1008 MHz、无线 NSS 关闭、普通 flowtable 未抢占 NSS，并检查真实加速计数。
3. 保留 HomeProxy 时的国内直连、名单代理、UDP/DNS 分流和现有节点测试/日志页面。
4. 在足够快的模拟 WAN/独立上游下，经实际 WAN/LAN 路径验证 ≥500 Mbps，记录持续时间与连接数。当前 300–350 Mbps 宽带自身不能直接完成这一项。
5. 家庭宽带满载时的 CPU/内存余量、管理面时延、丢包、代理核心是否重启，及 NAS 内网仍接近千兆。
6. 多小时混合负载、无线客户端离开再返回覆盖范围、冷启动及恢复。

NSS 不自动加速 sing-box 的加密协议；加密代理 500 Mbps 不包含在普通 NAT 验收结果中。低内存保护触发、短时通过或只有 NSS 模块名字，都不能记为“稳定 500 Mbps 已通过”。
