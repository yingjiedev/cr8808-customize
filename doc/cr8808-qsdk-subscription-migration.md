# QSDK 订阅迁移与 firewall4 影响评估

日期：2026-11-01。用户已授权评估并迁移订阅功能。当前实机仍运行已经确认默认启动的 QSDK 基础镜像 `1a3e589`；本页新增构建配置尚待 CI、镜像体积检查和实机迁移验收，不能当作已完成部署。

## 采用的迁移路线

保留 ARM32 / Linux 5.4.164 / QSDK NSS / fw3，集成 PassWall2 与一个静态 Xray 内核。透明代理、socket 匹配及其内核依赖重新纳入同次构建，不混用原 ARM64 或不同内核的软件包。普通直连流量通过 DNS 学习的 ipset 进行内核放行，实际 NSS 加速与代理接管仍须在设备上核验。

- PassWall2 固定提交 `d08e7f88fcb5c7f94b870f7281db0045a0477293`，版本 26.10.29。[原始构建配置](https://github.com/Openwrt-Passwall/openwrt-passwall2/blob/d08e7f88fcb5c7f94b870f7281db0045a0477293/luci-app-passwall2/Makefile)
- Xray 固定提交 `a4a3dff5b20c2faae567b742c172c7b95e75c083` / 26.10.31，静态 ARMv7 构建；同一内核支持原订阅使用的 VLESS、Hysteria2 与证书指纹验证。[固定源码](https://github.com/XTLS/Xray-core/tree/a4a3dff5b20c2faae567b742c172c7b95e75c083)
- Go 工具链固定为 1.27.3，并核对官方归档完整大小和 SHA256；它与实测官方 ARMv7 发布使用的工具链一致。Go 依赖沿用该提交的 `go.mod`、`go.sum`，构建禁止自动修改依赖。
- 保留 QSDK 本身和四个 feed 的固定提交。额外 tcping 配方固定原始源码提交与镜像摘要；其余用户态和内核依赖使用本次固件同批产物。

输入锁定文件见 [proxy/source-lock.json](../firmware/qsdk/proxy/source-lock.json)。CI 构建流程检查实际 ARM32 内核、模块、代理内核及 Lua 语法，使用 QEMU 执行生成内核的版本命令和实际 Xray 证书校验器的正负测试，再检查编译后的镜像与测试内核摘要一致。

## 单内核选择的实机依据

最初评估的 sing-box 1.12.25 ARM32 精简内核已通过首选 VLESS 的 HTTPS 测试，但首个 Hysteria2 节点被正常证书验证拒绝：证书仅有旧式 CN，订阅同时携带 `pinSHA256`。原 2026-10-27 检测记录中的 12 个 Hysteria2 节点也全部未通过。PassWall2 的 sing-box 生成器只有在 1.15 及以后才输出对应指纹选项，旧版本分支会改用 insecure；本轮没有采用该退化路径。核查时当前稳定 sing-box 为 1.14.4。

改用官方固定摘要的 Xray 26.10.31 ARM32 做隔离 SOCKS 测试，同一个进程中首选 VLESS 与带正确指纹的 Hysteria2 均取得 HTTPS 204；将指纹改错或删除后，两项负控制均失败，日志分别确认指纹不匹配和 CN 校验失败。没有启用通用 insecure，没有修改运行中的防火墙接管规则，测试结束已清理临时内核。

因此最终固件采用单个 Xray，从上述固定源码构建；官方发布二进制只用于前期隔离原型验证，不当作本仓库源码编译结果。CI 增加临时自签名旧式 CN 证书夹具，直接测试实际 Xray 校验器：正确叶证书指纹通过、错误指纹拒绝、没有指纹时保留常规校验。夹具不包含用户的节点或证书。

## 针对本机的裁剪

当前基础镜像 overlay 约剩 15.7 MiB。最初评估的官方 ARMv7 sing-box 展开约 39.4 MiB、压缩约 11.8 MiB；精简构建约 24.1 / 7.3 MiB。通过指纹测试的官方 Xray ARMv7 为 34,275,452 字节，独立 64 KiB XZ SquashFS 测量约 9.9 MiB；均还未包含界面和依赖，因此不在当前 overlay 上散装完整组件。

本轮将单个内核与应用集成到固件只读文件系统，SquashFS 使用 64 KiB 压缩块。配置、订阅及缓存继续位于持久 overlay；CI 检查 UBI 数据卷空间余量，最终可用容量以首启实机 `df` 为准。

为控制依赖，不安装 Geoview、GeoIP/GeoSite 大型数据库、多代理内核、HAProxy、SSR 和额外混淆程序。使用原有 GFW 域名列表迁移分流意图，不原样导入依赖缺失 Geo 数据的默认规则。PassWall2 已提供 dnsmasq ipset 辅助进程，因此不引入新版 ChinaDNS-NG 的额外兼容面。[上游 DNS 辅助实现](https://github.com/Openwrt-Passwall/openwrt-passwall2/blob/d08e7f88fcb5c7f94b870f7281db0045a0477293/luci-app-passwall2/root/usr/share/passwall2/app.sh)

OpenWrt 21.02 的 socket 扩展与 TPROXY 放在同一个包中；移除上游针对新系统单独选择的 `iptables-mod-socket`，检查实际内核仍包含 socket 匹配。保留 legacy iptables，删除会拉入 nft 后端的选择。

Xray 主服务使用 `GOGC=50`、`GOMEMLIMIT=32MiB`、`GOMAXPROCS=2`；`GOMEMLIMIT` 是 Go 的软目标，不是进程 RSS 的硬上限。加入 32 MiB zram 作为内存压力缓冲，不使用 NAND swap；运行内存、交换量和负载需实测。

公开默认配置不含订阅、节点或设备凭据，代理默认关闭。私有迁移包另行导入，先检查配置和单个节点，再启用流量接管。订阅内容不经过第三方在线转换服务。

## 升级 firewall4 会改变什么

| 项目 | 当前证据与影响 |
| --- | --- |
| 内核与软件包 | 实机及编译配置均显示 `CONFIG_NF_TABLES` 未启用；固定 QSDK 源码自带 nftables 0.9.6，未提供 fw4/ucode。需要新增并匹配整套依赖、重新编译内核，不能直接替换一个 IPK |
| 常规防火墙配置 | fw4 继续使用 UCI 防火墙格式，常见 zone、NAT、端口转发可作为迁移输入；自定义 iptables 命令、ipset、include 脚本及代理规则需要转换并验证 |
| NSS 转发 | fw4 本身不是 NSS 驱动，也不是吞吐升级。当前 QSDK ECM 配方明确依赖 iptables；这不能证明 nftables 必然不兼容，但同样没有证明当前 ECM 与新 nft 规则能正确协作，需要重新验证 NAT、加速计数、规则命中和代理绕过 |
| NAS 局域网 | 同桥同 VLAN 的硬件交换通常不经过 IP 防火墙，预期影响较小；跨 VLAN、经过路由或透明代理的流量另算 |
| HomeProxy | 满足 fw4、nft TPROXY、ucode digest 和相应 LuCI/rpcd API 后，可评估其 ARM32 适配；界面不是 ARM64 二进制，但原 ARM64 sing-box 无法复用。也不能将旧 nft 规则整套直接搬到 fw3 |
| 资源与恢复 | 需要重新测量空间、内存、DNS 和断网恢复，并保留现有工作系统；避免长期同时维护两套流量接管规则 |

fw4 共享 UCI 配置格式及其依赖见 [OpenWrt 官方配方](https://github.com/openwrt/openwrt/blob/main/package/network/config/firewall4/Makefile)；HomeProxy 依赖见 [项目配方](https://github.com/immortalwrt/homeproxy/blob/master/Makefile)。本机固定 QSDK 的 [ECM 配方](https://github.com/hzyitc/openwrt-redmi-ax3000/blob/ab1f9ffa5b5b62f252a5e87eb23f51f4e2544511/package/kernel/qca/qca-nss-ecm/Makefile) 仍依赖 iptables。该依赖也不意味着装有 iptables 就必然与 fw4 冲突；关键是实际生效规则与加速路径。上述均是源代码依据，不是 fw4 在本机已通过的实测结论。

两条路线都需要为当前基础镜像补齐透明代理内核模块，不能只以“需要重编译”为理由排除 fw4。fw4 的优势是与现代 OpenWrt 和 HomeProxy 使用相同的规则体系，可复用部分原应用配置与维护经验；额外工作主要是防火墙依赖回移、规则转换及 NSS 协作验证。当前继续完成 fw3 订阅迁移，缩小本轮变化范围；fw4/HomeProxy 可作为独立候选验证。

## 部署边界与待验收项目

- 当前 QSDK 原生升级会写入另一个系统槽。本轮若需要更新镜像，应先核对备份与启动槽，安排从保留系统写回 QSDK 槽，避免覆盖保留的恢复系统。
- 先验证启动、密码、持久化、双频和普通外网，再导入订阅、迁移原首选节点及 GFW 分流。
- 检查定时/手动订阅更新、错误更新保留可用配置、切换节点和 DNS 恢复。
- 重新测量国内直连 NSS 加速、NAS LAN 吞吐、代理实际出口、内存与 Wi-Fi 稳定性。现有 300–350 Mbps 宽带不能证明持续 500 Mbps NAT 上限。
- 11:54 左右观察到一次新的启动标识，用户回复不足以确认重启原因，已继续采集；不据此宣称长期稳定性通过。
