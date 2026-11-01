# QSDK 订阅迁移与 firewall4 影响评估

日期：2026-11-01。当前实机已刷入 `bbcfdb2`，完成 PassWall2 订阅迁移、默认启动接受及受控重启验证。保留 fw3/NSS，原 `rootfs_1` 的内核和只读根文件系统经刷后逐卷摘要核对保持不变。脱敏验收数据见 [实机迁移记录](validation/qsdk-subscription-bbcfdb2-20261101.json)。

## 采用的迁移路线

保留 ARM32 / Linux 5.4.164 / QSDK NSS / fw3，集成 PassWall2 与一个静态 Xray 内核。透明代理、socket 匹配及其内核依赖重新纳入同次构建，不混用原 ARM64 或不同内核的软件包。普通直连流量通过 DNS 学习的 ipset 进行内核放行；实机已验证代理接管以及国内下载时 NSS 加速计数增长。

- PassWall2 固定提交 `d08e7f88fcb5c7f94b870f7281db0045a0477293`，版本 26.10.29。[原始构建配置](https://github.com/Openwrt-Passwall/openwrt-passwall2/blob/d08e7f88fcb5c7f94b870f7281db0045a0477293/luci-app-passwall2/Makefile)
- Xray 固定提交 `a4a3dff5b20c2faae567b742c172c7b95e75c083` / 26.10.31，静态 ARMv7 构建；同一内核支持原订阅使用的 VLESS、Hysteria2 与证书指纹验证。[固定源码](https://github.com/XTLS/Xray-core/tree/a4a3dff5b20c2faae567b742c172c7b95e75c083)
- Go 工具链固定为 1.27.3，并核对官方归档完整大小和 SHA256；它与实测官方 ARMv7 发布使用的工具链一致。Go 依赖沿用该提交的 `go.mod`、`go.sum`，构建禁止自动修改依赖。
- 保留 QSDK 本身和四个 feed 的固定提交。额外 tcping 配方固定原始源码提交与镜像摘要；其余用户态和内核依赖使用本次固件同批产物。

输入锁定文件见 [proxy/source-lock.json](../firmware/qsdk/proxy/source-lock.json)。CI 构建流程检查实际 ARM32 内核、模块、代理内核及 Lua 语法，使用 QEMU 执行生成内核的版本命令和实际 Xray 证书校验器的正负测试，再检查编译后的镜像与测试内核摘要一致。

## 单内核选择的实机依据

最初评估的 sing-box 1.12.25 ARM32 精简内核已通过首选 VLESS 的 HTTPS 测试，但首个 Hysteria2 节点被正常证书验证拒绝：证书仅有旧式 CN，订阅同时携带 `pinSHA256`。原 2026-10-27 检测记录中的 12 个 Hysteria2 节点也全部未通过。PassWall2 的 sing-box 生成器只有在 1.15 及以后才输出对应指纹选项，旧版本分支会改用 insecure；本轮没有采用该退化路径。核查时当前稳定 sing-box 为 1.14.4。

改用官方固定摘要的 Xray 26.10.31 ARM32 做隔离 SOCKS 测试，同一个进程中首选 VLESS 与带正确指纹的 Hysteria2 均取得 HTTPS 204；将指纹改错或删除后，两项负控制均失败，日志分别确认指纹不匹配和 CN 校验失败。没有启用通用 insecure，没有修改运行中的防火墙接管规则，测试结束已清理临时内核。

因此最终固件采用单个 Xray，从上述固定源码构建；官方发布二进制只用于前期隔离原型验证，不当作本仓库源码编译结果。CI 增加临时自签名旧式 CN 证书夹具，直接测试实际 Xray 校验器：正确叶证书指纹通过、错误指纹拒绝、没有指纹时保留常规校验。夹具不包含用户的节点或证书。

候选 `14badda` 的 [CI](https://github.com/yingjiedev/cr8808-customize/actions/runs/41274667392) 已通过配置检查、ARM32 内核编译、QEMU 版本执行及证书正负测试，产生提前上传的代理内核产物。下载后核对归档摘要、源码锁和 ELF 摘要，并在当前路由器上重复上述四项实际 HTTPS 控制，全部符合预期。该源码编译 ELF 为 30,474,364 字节、独立 64 KiB XZ SquashFS 为 9,203,712 字节；四项短连接测试后进程 RSS 30,084 KiB，设备 MemAvailable 38,888 KiB。这不是透明代理或持续吞吐结果；测试服务与临时内核已经清理。脱敏证据见 [实机内核验证记录](validation/qsdk-proxy-core-20261101.json)。

## 针对本机的裁剪

当前基础镜像 overlay 约剩 15.7 MiB。最初评估的官方 ARMv7 sing-box 展开约 39.4 MiB、压缩约 11.8 MiB；精简构建约 24.1 / 7.3 MiB。通过指纹测试的官方 Xray ARMv7 为 34,275,452 字节，独立 64 KiB XZ SquashFS 测量约 9.9 MiB；均还未包含界面和依赖，因此不在当前 overlay 上散装完整组件。

本轮将单个内核与应用集成到固件只读文件系统，SquashFS 使用 64 KiB 压缩块。配置、订阅及缓存继续位于持久 overlay；CI 检查 UBI 数据卷空间余量，最终可用容量以首启实机 `df` 为准。

为控制依赖，不安装 Geoview、GeoIP/GeoSite 大型数据库、多代理内核、HAProxy、SSR 和额外混淆程序。使用原有 GFW 域名列表迁移分流意图，不原样导入依赖缺失 Geo 数据的默认规则。PassWall2 已提供 dnsmasq ipset 辅助进程，因此不引入新版 ChinaDNS-NG 的额外兼容面。[上游 DNS 辅助实现](https://github.com/Openwrt-Passwall/openwrt-passwall2/blob/d08e7f88fcb5c7f94b870f7281db0045a0477293/luci-app-passwall2/root/usr/share/passwall2/app.sh)

OpenWrt 21.02 的 socket 扩展与 TPROXY 放在同一个包中；移除上游针对新系统单独选择的 `iptables-mod-socket`，检查实际内核仍包含 socket 匹配。保留 legacy iptables，删除会拉入 nft 后端的选择。

Xray 主服务使用 `GOGC=50`、`GOMEMLIMIT=32MiB`、`GOMAXPROCS=2`；`GOMEMLIMIT` 是 Go 的软目标，不是进程 RSS 的硬上限。加入 32 MiB zram 作为内存压力缓冲，不使用 NAND swap；运行内存、交换量和负载需实测。

公开默认配置不含订阅、节点或设备凭据，代理默认关闭。私有迁移包另行导入，先检查配置和单个节点，再启用流量接管。订阅内容不经过第三方在线转换服务。

`14badda` 的完整编译成功，但最后检查先遇到旧版 squashfskit 不支持 `-cat` 的问题。独立解包继续复核后发现默认打包器还会对 Go ELF 执行二次 sstrip，导致镜像中的 Xray 与 QEMU/实机测试版本摘要不同。因此没有部署该镜像：检查器改用旧工具支持的目录提取方式，静态 Xray 配方关闭二次裁剪，并继续要求镜像内核与已测试 ELF 的 SHA256 完全一致。

固定上游的订阅与组件下载默认 curl 参数带有 `-k`。本轮明确移除该参数，保留 HTTPS 的 CA 与主机名验证；节点自身的证书指纹验证不受此修改影响。订阅下载失败时不以跳过 TLS 校验作为回退。

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

两条路线都需要为当前基础镜像补齐透明代理内核模块，不能只以“需要重编译”为理由排除 fw4。fw4 的优势是与现代 OpenWrt 和 HomeProxy 使用相同的规则体系，可复用部分原应用配置与维护经验；额外工作主要是防火墙依赖回移、规则转换及 NSS 协作验证。本轮已完成 fw3 订阅迁移，缩小本轮变化范围；fw4/HomeProxy 可作为独立候选验证。

## 实机验收与使用边界

最终镜像的 [完整 CI](https://github.com/yingjiedev/cr8808-customize/actions/runs/41289823028) 全部通过。工厂 UBI 为 23,855,104 字节，SHA256 为 `2595c264f0fbbd38f9f5fd32781cefa24bf88648e81e88ffee694f30a3f84ef2`；镜像中的 Xray 与实测 ELF 摘要一致。先切入保留系统，从该系统原生升级写回 `rootfs`；未调整分区、未写引导程序，原 `rootfs_1` 保留。

- 原网络、双频 Wi-Fi、密码、SSH 主机密钥和 uhttpd 并发设置保留；重启前后 10 个配置或凭据文件的摘要全部相同。重启后双频均观察到实际客户端连接。
- 原生导入 49 条订阅条目：29 条 VLESS、20 条 Hysteria2，包含节点别名；20 个证书指纹均保留。原首选 VLESS 和 4443 条 GFW 域名分流生效，默认直连。
- 实际切换至 Hysteria2，通过 HTTPS 204 测试后恢复原首选 VLESS。手动更新重新导入节点并正确更新首选引用；模拟不可达订阅后，配置文件逐字节不变，代理保持运行。自动订阅更新沿用原设置关闭。
- PassWall2 设置、节点、订阅三个认证页面均返回 200，无 Lua 异常。入口为路由器 LuCI 的「服务 → PassWall 2」。
- 已接受为默认 `rootfs`，恢复固件原生启动脚本。受控重启后仍是该镜像、订阅与分流自动运行，无试用回退计时器；最终设置和启动环境已再次备份到本机私有目录。

| 代理开启时的检查 | 实测 |
| --- | --- |
| 国内下载，重启前 60 秒 | 294.23 Mbps，双核平均忙碌约 11.02% |
| 国内下载，重启后 30 秒 | 291.01 Mbps，双核平均忙碌约 8.36%，可用内存最低约 38.2 MiB |
| 重启后下载期间 NSS 加速字节增量 | 1,211,845,248 字节，计数采样完整覆盖该次下载 |
| NAS 大文件只读，客户端绕过文件缓存，60 秒 | 922.69 Mbps / 115.34 MB/s，客户端网卡错误和丢弃增量均为 0 |
| NAS 重启后 30 秒复核 | 915.81 Mbps；开头同时通过电脑网卡读取了一份约 36 MiB 的路由器备份，错误和丢弃增量仍为 0 |
| 最终空间与内存缓冲 | overlay 剩余 7040 KiB；32 MiB zram 已启用，最终交换用量 512 KiB |

本次短时检查未观察到 Oops、内核 panic、OOM、Wi-Fi 固件崩溃或 NAND ECC 错误。基础镜像在 11:54 曾出现一次原因未确认的重启；本轮刷写与验收重启均由本次流程主动安排。新镜像尚未完成长期运行观察。现有宽带下行 300 Mbps、峰值约 350 Mbps，不能据此证明持续 500 Mbps NAT 或加密代理吞吐。

后续 QSDK 原生升级仍会写入另一个系统槽。若要继续保留恢复系统，应沿用核对备份与活动槽、从保留系统写回 QSDK 槽的流程。

## 首页 Google 检测的后续修复

2026-11-01 刷后使用中，发现首页 Google 检测失败。初始现场的电脑经路由器访问 Google 返回 HTTPS 204，但路由器自身请求超时：迁移默认值设置了 `client_proxy=1`、`localhost_proxy=0`。首页 `connect_status` 接口在路由器上运行 curl，因此启用客户端节点不足以让这个检测走代理。本轮已启用并持久保存「本机代理」，公开默认配置也同步改为 `localhost_proxy=1`；公开镜像的总开关仍为关闭，需用户配置后启用。

进一步对照发现，原首选 VLESS 节点有超过 3 秒的成功握手，也有 TLS 断连。上游首页检测只有 3 秒连接预算，因此将连接超时改为 8 秒、总时限设为 12 秒；真实不可达目标仍返回检测失败。当前私有 GFW 分流切至对照较稳定的日本专线 Hysteria2 节点，沿用 0.1 倍率，保留证书指纹验证；节点、订阅地址和证书指纹不写入公开配置。这是短时对照结果，不能视为节点长期可用性保证。

保留旧 `/etc/config/firewall` 时还遗漏了上游应用新建的 `firewall.passwall2` 加载项。现场已按原生设置补回 script include `/var/etc/passwall2.include`、`reload=1`；代理重建后进行了实际 firewall reload，代理规则和原 Xray 进程均保留，首页和客户端访问再次通过。以后迁移旧配置须合并此加载项，避免覆盖应用安装时创建的条目。

现场仅修改应用文件和 UCI 配置，没有再次刷写或重启路由器。源码构建器固定并核对控制器源码摘要，在打包阶段应用检测超时修复，并在镜像检查阶段校验本机代理默认值、超时参数及控制器 Lua 语法。当前固件标识仍为 `bbcfdb2`，以上为其刷后的现场修正；脱敏复核见 [Google 检测修复记录](validation/qsdk-passwall2-google-20261101.json)。
