# CR8808 主路由、订阅接入与分流配置调研

调研日期：2026-10-26。目标：**CR8808 作为主路由，接管全家网络；同时覆盖 Clash/Mihomo 和通用节点订阅。** 本次完成本地记录复核、上游文档/源码核查、软件包下载及离线校验，没有登录路由器、安装软件、修改网络、刷写或重启。

2026-10-27 实施补充：已采用 HomeProxy + 压缩只读 sing-box 应用镜像完成主路由、无线和订阅预配置，步骤、实测结果与待验收项目见[配置手册](cr8808-main-router-configuration-manual.md)。下文保留调研时的判断和数据。

## 1. 结论与建议

主路由功能可以继续在已安装的 ImmortalWrt 上配置。实现顺序应为：**WAN 正常上网 → LAN/DHCP/无线 → 代理运行环境 → 订阅和规则 → DNS/透明代理 → 全家切换与验收。**

- 如果以 Clash 规则、策略组和完整订阅配置为主，优先考虑 **OpenClash + Mihomo**。当前 Mihomo 的代理集合也支持 URI/Base64 通用订阅，不必为两种格式同时运行两套插件。[OpenClash](https://github.com/vernesong/OpenClash)、[代理集合格式](https://wiki.metacubex.one/config/proxy-providers/content/)
- 如果以逐节点管理、按设备配置为主，可以考虑 **PassWall2 + 一个所需内核**。它并不天然比 OpenClash 省空间；当前构建选项可能同时带上多个内核和 Geo 数据，需要主动裁剪。[PassWall2 构建配置](https://github.com/Openwrt-Passwall/openwrt-passwall2/blob/main/luci-app-passwall2/Makefile)
- **本机目前的主要限制是持久存储。** 不能直接照通用教程安装当前完整 OpenClash。建议先验证普通主路由，再对精简固件/精简组件做实际体积评估；完整插件能否长期运行，需要据此决定。

“订阅”提供节点或配置，不等于路由器固件。路由器还需要代理内核、流量接管和 DNS 配置；导入成功不代表全家流量已经经过代理。

## 2. 本机现状与实际限制

### 2.1 已有实机证据

以下来自 2026-10-25 的[刷机实操记录](cr8808-openwrt-hands-on.md)及本地 `tmp/device-info/postflash-verification.json`，不是本次重新读取的实时状态。

| 项目 | 已有记录 | 对本次配置的影响 |
| --- | --- | --- |
| 系统 | ImmortalWrt `24.10-SNAPSHOT r0-9a11bb8` | 按该构建匹配软件包 |
| 内核/目标 | `6.6.137`，`qualcommax/ipq50xx` | kmod 必须连 ABI 一起匹配 |
| 架构 | ARM64；本构建软件包为 `aarch64_cortex-a53` | Mihomo 选 Linux ARM64；IPK 依赖选对应架构 |
| 当前系统槽 | `mtd19 / rootfs_1`，36 MiB | 全部 NAND 容量不等于当前系统可用容量 |
| 可写空间 | `/overlay` 总计约 12.8 MiB，记录可用约 12.0 MiB | 完整代理组件明显受限 |
| 内存 | 启动日志：物理 256 MiB，内核报告约 179 MiB available | 这是启动时数据，不是当前 `MemAvailable` |
| 管理/无线 | `192.168.1.1`；两路无线已关闭 | 配置好 SSID 和加密后再启用 |
| 外网/性能 | WAN 未测试；电脑 LAN 链路曾为 100 Mbps | 不能据现有记录承诺代理吞吐 |

### 2.2 本次下载测量

从项目正式发布页获取以下文件，SHA256 与 GitHub Release API 提供的 digest 一致；只解析归档及二进制头，没有执行下载内容。

| 组件 | 下载包字节数 | 展开内容字节数 | 说明 |
| --- | ---: | ---: | --- |
| Mihomo `v1.19.33` Linux ARM64 | 20,824,326，约 19.86 MiB | 57,475,198，约 54.81 MiB | 单个 ELF 内核，不含界面和规则数据 |
| OpenClash `v0.48.002` IPK | 10,710,754，约 10.21 MiB | 文件内容合计 28,843,373，约 27.51 MiB | 包含 GeoSite 和面板资源；不含 Mihomo 内核及外部依赖 |

来源：[Mihomo 固定发布版本](https://github.com/MetaCubeX/mihomo/releases/tag/v1.19.33)、[OpenClash 固定发布版本](https://github.com/vernesong/OpenClash/releases/tag/v0.48.002)。展开大小不是 UBIFS 最终占用，也不是进程内存；但这些数据足以说明，现有约 12 MiB 可写空间不能作为当前完整组合常规安装的容量预算。

本地测量证据：`tmp/subscription-research/mihomo-size-verification.json`、`openclash-size-verification.json`、`upstream-versions.json`。

### 2.3 依赖和软件源已经核查到什么程度

本次下载了与已刷镜像同一 Release 的 manifest，并核对公布的 SHA256：`c2f2c184a85fd3993a37d068b2fa312ecdd041cde25a3b0d1794fe50b7baf5ba`。该清单包含 `dnsmasq-full`、`firewall4`、`luci-compat`、`opkg` 和 PPPoE 组件；没有包含 OpenClash 所需的全部额外依赖。**这台机器不需要照其他教程先卸载普通 dnsmasq。** 来源：[本机固件 Release](https://github.com/kmiit/Redmi_AX3000_immortalwrt/releases/tag/ci-redmi_ax3000-24.10-20260716-145815-UTC)。实际安装前仍应读取本机已安装清单。

本构建完整内核版本为：

```text
6.6.137~20a052f3c3e98b3a9ba1a095f81e2725-r1
```

在发布者保留的 `r0-9a11bb8` 软件源中，已找到 `kmod-tun`、`kmod-nft-tproxy`、`kmod-nft-socket`、`kmod-inet-diag` 及两个关联模块。六个文件均已下载，长度和 SHA256 与索引一致，依赖中的内核 ABI 与上述版本一致。**这证明有匹配候选包，不代表已上机加载通过，也不代表全部用户态依赖已验证。** [对应软件源索引](https://raw.githubusercontent.com/kmiit/Redmi_AX3000_immortalwrt/gh-pages/redmi_ax3000-24.10/r0-9a11bb8/Packages)

不要因为同为 `6.6.137` 就混装其他构建的 kmod；遇到 ABI 不符应取得匹配包，不能靠 `--force-depends` 解决。[OpenWrt 内核依赖说明](https://openwrt.org/faq/cannot_satisfy_dependencies)

## 3. 主路由接线与基础配置

推荐最终拓扑：

```text
互联网 ─ 光猫（桥接）─ CR8808 WAN
                         ├─ LAN ─ 电脑/交换机/有线设备
                         ├─ Wi-Fi ─ 手机/平板/电视
                         └─ LAN ─ 原有路由器（AP 模式）
```

如果光猫继续负责上网，CR8808 WAN 使用 DHCP，仍可统一管理其下游家庭网络，但会形成上游路由加本机路由的结构。所有要受本机规则管理的设备，都要接在 CR8808 的 LAN/无线侧。

### 3.1 WAN 按现有宽带方式选择

| 当前上网方式 | CR8808 WAN 协议 | 需要的信息 |
| --- | --- | --- |
| 光猫桥接、路由器拨号 | PPPoE | 宽带账号密码；运营商是否要求 VLAN/MAC 等 |
| 光猫路由模式、插线自动上网 | DHCP 客户端 | 上游网段；本机 LAN 要与其错开 |
| 运营商直接提供 DHCP 接入 | DHCP 客户端 | 可能有 VLAN 或 MAC 绑定 |
| 已分配固定地址 | 静态地址 | 运营商给出的地址、掩码、网关和 DNS |

在 LuCI“网络 → 接口 → WAN”中配置。接口对应的物理设备沿用本机构建，不能从别的设备教程照抄 `eth0`、`eth1` 或交换机端口号。PPPoE 的 MTU 先沿用协议默认值；VLAN/IPTV 配置依据现有宽带信息单独处理。[OpenWrt 网络接口与协议](https://openwrt.org/docs/guide-user/network/network_configuration)

### 3.2 LAN、DHCP、无线和原有 AP

下面是规划示例，实施前核对光猫、VPN 和电脑虚拟网卡是否占用该网段：

| 设置 | 示例 |
| --- | --- |
| CR8808 LAN | `192.168.8.1/24` |
| DHCP 地址池 | `192.168.8.100`–`192.168.8.199` |
| 家庭终端网关 | `192.168.8.1` |
| 家庭终端 DNS | `192.168.8.1` |
| 原有路由器/AP 管理地址 | 例如 `192.168.8.2`，保留地址避免冲突 |

CR8808 保持 LAN DHCP 服务；原有路由器设 AP 模式，让本机统一分配网关和 DNS。采用手动 LAN–LAN 接法时，原有路由器需关闭 DHCP；原生 AP 模式的接入口按其设备说明选择。修改本机 LAN 地址后，电脑重新获取地址，并通过新地址登录。

无线分别设置 SSID 和 WPA2/WPA3 密码后再启用。保留现有 LAN→WAN 转发和 WAN NAT；管理界面及代理控制接口仅供可信内网使用。DHCP/DNS 的网关及 DNS 下发依据：[OpenWrt DHCP 配置](https://openwrt.org/docs/guide-user/base-system/dhcp)。

## 4. Clash 和通用订阅如何接入

### 4.1 先区分返回的内容

| 订阅内容 | 如何使用 |
| --- | --- |
| 完整 Clash YAML，含节点、策略组、规则等 | 由 OpenClash 下载/导入完整配置，再用本地覆写保留家庭设置 |
| 只有 `proxies:` 的 YAML | 放入 Mihomo `proxy-providers`，策略组和分流规则由本地配置提供 |
| 多行 `ss://`、`vmess://`、`vless://`、`trojan://` 等 | 当前 Mihomo provider 可解析其支持的节点 URI；也可交给 PassWall2 节点订阅解析 |
| 上述 URI 列表整体 Base64 编码 | 当前 Mihomo provider 可解码解析；PassWall2 也有相应订阅解析逻辑 |
| sing-box JSON | 按对应 sing-box 版本配置处理，不当作完整 Clash YAML 导入 |

Mihomo 文档明确列出 YAML、URI、Base64 三种 provider 内容格式。本次还检查了 `v1.19.33` 的 [provider 解析器](https://github.com/MetaCubeX/mihomo/blob/v1.19.33/adapter/provider/provider.go)和 [URI 转换实现](https://github.com/MetaCubeX/mihomo/blob/v1.19.33/common/convert/converter.go)，确认并非仅依赖开发分支文档。URI、Base64 节点列表不需要加 `proxies:`；不要混合三种格式。[格式说明](https://wiki.metacubex.one/config/proxy-providers/content/)

兼容性仍取决于具体协议、传输方式和订阅字段，不能保证所有提供商的扩展字段无损导入。服务器可能根据请求头返回不同格式，需用实际下载内容和解析结果确认。PassWall2 的支持情况见其[订阅解析源码](https://github.com/Openwrt-Passwall/openwrt-passwall2/blob/main/luci-app-passwall2/root/usr/share/passwall2/subscribe.lua)；sing-box 使用 JSON 配置，版本变化需按其文档处理。[sing-box 配置说明](https://sing-box.sagernet.org/configuration/)

### 4.2 推荐把节点更新与家庭规则分开

对于需要长期保留家庭分流规则的情况，可维护一份本地配置，通过 provider 更新节点。下面仅演示 provider 与策略组的连接，**不是完整的透明代理配置**，缺少 DNS、分流规则和流量接管部分。

```yaml
proxy-providers:
  family:
    type: http
    url: "https://subscription.example.invalid/replace-me"
    path: ./proxy_provider/family.yaml
    interval: 86400
    proxy: DIRECT
    health-check:
      enable: true
      url: https://www.gstatic.com/generate_204
      interval: 600

proxy-groups:
  - name: 自动选择
    type: url-test
    use:
      - family
    url: https://www.gstatic.com/generate_204
    interval: 600
  - name: 代理出口
    type: select
    proxies:
      - 自动选择
      - DIRECT
    use:
      - family
```

替换为自己的订阅后，同一结构可接入兼容的 YAML、URI 或 Base64 节点源。示例采用直连下载，必须确认订阅域名能直连；如果只能通过代理下载，需要保留可用缓存/引导节点，避免启动时相互依赖。更新频率和测速间隔是建议初值，可按节点数量调整。[provider 参数](https://wiki.metacubex.one/config/proxy-providers/)

如果使用提供商的完整 Clash 配置，操作路径是 OpenClash 的订阅/配置管理：新增订阅、下载、检查配置、选择当前文件、启动并检查日志。本地 DNS、设备规则等放在插件覆写机制中；直接修改下载文件，下一次订阅更新可能被覆盖。[OpenClash 使用入口](https://github.com/vernesong/OpenClash)

### 4.3 什么时候需要订阅转换

优先使用提供商原生 Clash/Mihomo 导出或内核原生 provider 解析。只有目标客户端不支持其输入格式、或确实需要生成完整策略配置时，再考虑转换。

OpenClash 保留在线订阅转换选项，但它不是导入通用订阅的唯一方式。需要转换时可在自己的电脑/服务器上运行转换器；第三方转换服务会接触原订阅 URL。完整订阅、节点密码及 token 放在路由器本地或忽略目录，不写入本项目文档和 Git。[OpenClash 转换选项源码](https://github.com/vernesong/OpenClash/blob/v0.48.002/luci-app-openclash/luasrc/model/cbi/openclash/config-subscribe-edit.lua)

## 5. 全家透明代理、DNS 与 IPv6

“Rule/规则模式”决定使用哪个出口；“TUN/TPROXY/重定向”决定如何把终端流量交给内核，这是两层不同设置。只设置浏览器 HTTP 代理，不能覆盖电视、游戏和其他应用。

建议首版由一个插件统一维护透明代理和 DNS 接管，不叠加多套代理防火墙脚本。实际选择 TPROXY、TUN 或插件组合模式，要同时覆盖需要处理的 TCP/UDP，并核对对应模块；不要把 TCP 重定向成功当作 UDP 已通过。当前 Firewall4 路线使用 nftables 相关模块。[OpenClash 依赖](https://github.com/vernesong/OpenClash/blob/master/luci-app-openclash/Makefile)、[Mihomo TUN 配置](https://wiki.metacubex.one/config/inbound/tun/)

建议 DNS 路径为：

```text
终端 → CR8808 的 DNS 服务 → 代理内核 DNS → 按策略使用上游 DNS
```

由插件协调 dnsmasq 与内核监听端口，避免两个进程争抢 53，或 dnsmasq 与内核互相转发形成循环。Fake-IP 可配合域名规则；局域网域名、打印机、NAS 和出现兼容问题的应用按需加入例外。上游 DNS 的连接也应符合分流策略，代理服务器域名要有能独立工作的解析路径。[Mihomo DNS 参数](https://wiki.metacubex.one/config/dns/)

本地规则建议先覆盖：家庭网段和局域网域名直连、指定服务直连/代理、需要的地区规则、明确的兜底出口。某些电视、IoT 可配置设备级直连；需要较强隔离时再划分独立网络。先使用少量必要规则，避免大量 Geo 数据和频繁全节点测速消耗资源。

IPv6 应单独验收：WAN 获得 IPv6 地址不等于 LAN 已获得可用委派前缀；客户端可能通过 IPv6 选择不同出口。初次验证可以暂不向 LAN 提供公网 IPv6，IPv4 稳定后再配置前缀委派、RA/DHCPv6 和对应代理规则。**仅设置 Mihomo `dns.ipv6: false` 不会关闭客户端已有的 IPv6 通路。** [OpenWrt IPv6 配置](https://openwrt.org/docs/guide-user/network/ipv6/configuration)

常规 53 端口 DNS 接管也不能自动控制所有 DoH/DoT。验收时检查浏览器安全 DNS、手机私人 DNS 和硬编码 DNS 的实际行为，不把一次网页访问成功当作完整 DNS 验证。

## 6. 存储方案如何选

| 路线 | 适用性与下一步 |
| --- | --- |
| 当前系统直接安装完整 OpenClash + 当前 Mihomo | 不作为本机可执行方案；完整组合及依赖超出当前可写空间预算 |
| 精简固件，把必要组件放进 SquashFS | **优先做体积试构建。** 只选一个内核、必要协议和小规则集；裁剪冗余面板/数据，检查最终镜像、升级余量和 36 MiB 槽位约束。不能预先承诺能装下完整 OpenClash |
| 精简 sing-box + HomeProxy 或自行维护服务 | 候选路线；减少界面/多内核依赖，但要实际量体积并验证所需订阅协议。HomeProxy 仍依赖 sing-box、Firewall4 和 TPROXY 模块，不代表可以直接装下。[构建配置](https://github.com/immortalwrt/homeproxy/blob/master/Makefile) |
| 把代理内核放 `/tmp` | 适合短期原型评估；占 RAM，断电清空，启动需恢复内核，更新还需要临时空间 |
| 调整 NAND 数据区/系统布局 | 独立研究项；现有 `mtd20/mtd21` 并非已经挂载的空闲应用盘，可能含原厂数据，不能凭分区名称格式化 |

OpenClash 的 `small_flash_memory` 确实可把内核位置改到 `/tmp/etc/openclash/core`，但它不会自动解决插件自身、依赖和全部规则资源的容量问题。以本次 54.81 MiB 内核为例，RAM 文件占用之外还要预算进程、规则和更新临时副本，不能把它当作长期主路由的现成解决办法。[固定版本内核路径逻辑](https://github.com/vernesong/OpenClash/blob/v0.48.002/luci-app-openclash/root/usr/share/openclash/openclash_core.sh)

网页 U-Boot 的恢复功能与系统可写容量是不同问题。当前订阅调研不以更换引导为前提，也不把现有原厂槽位或备份数据纳入可用空间。

## 7. 建议实施顺序与验收

1. **实施前重新盘点。** 读取当前空间、内存、WAN 协议、端口映射、软件源和包清单；本报告里的实机状态来自前一天。
2. **完成普通主路由。** 在维护窗口按现有宽带方式配置 WAN、LAN、DHCP、无线，先确认不运行代理也能正常上网。留存原路由器接线和配置，便于恢复。
3. **确定存储实现。** 对精简镜像或精简组件做实际容量验证，所需依赖全部匹配后才安装/刷写。镜像构建成功不能替代本机启动验证。
4. **先验证单终端。** 导入订阅、验证配置、确认节点能连接；再逐项启用透明代理、DNS 和分流。
5. **验证全家设备。** 检查电脑、手机、电视、IoT、局域网访问、UDP、IPv6 和必要的 IPTV；保留设备直连例外。
6. **验证恢复与故障行为。** 检查订阅更新失败后是否保留可用配置、节点故障后如何切换，以及停止代理后 DNS 能否恢复。普通直连服务可恢复，不等于要求代理的流量应自动直连；后者按规则目标选择阻断或备用代理。
7. **最后做重启和持续负载测试。** 验证重启后 WAN、DHCP、DNS 和代理恢复；记录 CPU、`MemAvailable`、OOM 日志、可写空间和实际吞吐。按本项目既有维护条件安排重启。

未来盘点可在路由器 SSH 执行以下只读命令；本次没有执行：

```sh
ubus call system board
uname -r
df -h /overlay /tmp
free -m
opkg print-architecture
opkg list-installed | grep -E '^(kernel|dnsmasq(-full)?|firewall4|kmod-(tun|nft-tproxy|nft-socket|inet-diag)|luci-app-(openclash|passwall2|homeproxy)|sing-box|xray-core) '
uci -q get network.wan.proto
uci -q get network.wan.device
ip route show default
dnsmasq --version
```

最终验收应看到：终端拿到本机网关和 DNS；直连和代理服务各走预期出口；停止代理后的恢复行为符合目标；重启后服务可恢复；常用家庭设备、UDP/IPv6 测试通过。测速前先解决电脑此前的 100 Mbps 协商问题，区分普通路由、直连分流和加密代理吞吐。

当前尚未确认的实施信息是：宽带由谁拨号、是否有 VLAN/IPTV、最终需要哪些节点协议、最新设备空间/内存，以及精简方案的实际体积。这些不影响上述架构结论，但会决定最终可执行配置。
