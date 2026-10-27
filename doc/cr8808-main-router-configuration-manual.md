# CR8808 主路由、Wi-Fi 与订阅配置手册

配置日期：2026-10-27。状态：**已修正主路由接线并安装 HomeProxy 页面超时补丁；WAN DHCP、电脑基本外网访问和页面加载接口验证通过，持续负载等项目待验收。**

本次在现有 ImmortalWrt 上配置 DHCP 主路由、双频无线、HomeProxy 和 sing-box。操作前已备份；没有刷写固件、修改分区或重启设备。管理员密码、Wi-Fi 密码、订阅地址及节点凭据不写入本手册。

## 1. 现在怎样使用

1. 打开 **http://192.168.1.1**，使用现有 `root` 管理员密码登录。
2. 手机/电脑可连接 **`HA-NEW`**，密码为这次在本机输入框中设置的 Wi-Fi 密码。
3. 订阅、节点和分流入口在 **服务 → HomeProxy**。已导入节点，可在客户端设置里切换主节点或自动选择候选。
4. 将光猫或上级路由器的 **LAN 口 → CR8808 的 WAN 口**，电脑和家庭终端接本机 LAN/无线。当前 WAN 已获取 `192.168.71.18`，代理运行中；重新断线、上线触发流程仍需单独验收。

家庭终端应连接本机 LAN/无线侧，自动获取网关和 DNS。原有路由器若用于扩展覆盖，可改为 AP 模式，统一由 CR8808 分配地址。

```text
光猫 / 上级路由器 LAN ── CR8808 WAN（DHCP）
                            ├─ LAN：电脑、交换机、AP
                            └─ Wi-Fi：HA-NEW（2.4 GHz / 5 GHz）
```

当前方案保留上级设备的路由功能；如果今后把光猫改为桥接，需要另行把本机 WAN 改为 PPPoE，并填写宽带账号等信息。

## 2. 本次实际配置

| 项目 | 当前设置 |
| --- | --- |
| 固件 | ImmortalWrt `24.10-SNAPSHOT r0-9a11bb8`，内核 `6.6.137` |
| 主机名 | `CR8808` |
| LAN / 管理地址 | `192.168.1.1/24` |
| DHCP 地址池 | `192.168.1.100`–`192.168.1.249`，租期 12 小时 |
| 终端网关、DNS | 由本机 DHCP 下发本机地址 |
| WAN | 设备 `wan`，DHCP 客户端、自动启动 |
| 5 GHz | `HA-NEW`，信道 36，HE80 |
| 2.4 GHz | `HA-NEW`，信道 1，HE20 |
| 无线加密 | `sae-mixed`：WPA2/WPA3 混合，PMF 可选 |
| IPv6 | 暂停 WAN6 自动启动；LAN RA、DHCPv6、NDP 通告关闭 |
| 代理界面 | HomeProxy `26.236.50592~9b8ee64`，已安装中文翻译 |
| 代理内核 | sing-box `1.12.25`；本地包 `sing-box-squashfs 1.12.25-r2` |
| 分流 | 中国大陆流量绕过代理；其余按 HomeProxy 规则处理 |
| 接管 | TCP Redirect + UDP TPROXY，目标端口不设筛选 |
| DNS | 代理侧 `https://1.1.1.1/dns-query`；中国大陆侧 `223.5.5.5` |
| 主出口 | 3 个 VLESS 候选自动选择；每 600 秒检测，容差 50 ms |
| UDP 出口 | 跟随主出口 |
| 流量分载 | 软件、硬件 flow offloading 均关闭 |
| 订阅定时更新 | 暂未开启；先完成联网验收，再在订阅页设置 |

**HomeProxy 的“所有端口”对应空值/删除 `routing_port`，不是字符串 `all`。** 本次已按实际界面和 nftables 模板核实，并通过防火墙语法检查。

当前 LAN 地址与上级网段必须不同。如果以后连接的光猫/路由器也使用 `192.168.1.0/24`，先在“网络 → 接口 → LAN”中把本机改到一个不冲突的网段，例如核对后使用 `192.168.8.1/24`，再重新获取终端地址并通过新地址登录。

## 3. 订阅接入结果与后续维护

本次订阅返回 **Base64 编码的通用 URI 列表**。电脑端通过正常 HTTPS 下载，未提交给在线转换服务；随后通过 SSH 把内容交给路由器自身的 HomeProxy 解析器导入。

| 阶段 | 结果 |
| --- | --- |
| 下载内容统计 | 54 条 URI：20 条 Hysteria2、34 条 VLESS |
| HomeProxy 解析/去重后保存 | 42 个节点：12 个 Hysteria2、30 个 VLESS |
| 原生导入日志 | 成功更新；记录了 9 次重复节点跳过 |
| 当前自动选择候选 | 3 个 VLESS 节点 |

上表不是对全部节点连通性的验证。HomeProxy 未保留的条目不计入可用节点；本次也没有通过 WAN 测试任一出口。

联网后，在 HomeProxy 的订阅页点击更新，确认节点仍能解析，再测试出口。需要自动更新时，设置更新时刻；更新后检查当前主节点及自动选择候选仍然有效。

当前保存的是原订阅 URL，未来更新由 HomeProxy 自行下载。若换成完整 Clash YAML，应使用提供商的通用节点导出格式，或先选用支持该配置格式的客户端；**本次安装没有把 HomeProxy 扩展为 Clash YAML 解析器。** 格式比较见[订阅与主路由调研](cr8808-subscription-main-router-research.md)。

Wi-Fi 密码和订阅 URL 保存在本机受限输入目录及路由器配置中。原生订阅更新日志可能显示订阅地址，分享日志前应先脱敏；不要公开 `/etc/config/homeproxy` 或 `/etc/config/wireless` 的完整内容。

## 4. 这台机器怎样容纳代理内核

本机 `/overlay` 总计约 12.8 MiB，常规安装完整插件和展开的代理内核不合适。本次采用 **HomeProxy + 压缩只读 sing-box 应用镜像**。

```text
/usr/share/sing-box-squashfs/core.squashfs  （持久保存，约 7.33 MiB）
                 │ loop + SquashFS 只读挂载
                 ▼
/tmp/sing-box-squashfs/sing-box
                 │ 文件 bind mount
                 ▼
/usr/bin/sing-box                         （正常 ELF 路径，供 HomeProxy/ujail 使用）
```

这里 `/tmp/sing-box-squashfs` 是挂载点，不是在 RAM 中展开一个 28 MiB 文件。内核直接读取压缩文件系统；运行时仍会消耗代码页、缓存和进程内存。启动无需联网下载内核。

| 校验对象 | SHA256 |
| --- | --- |
| 原始 `sing-box-tiny` IPK | `bdd93e62ef2d4351fa9a5f9e8a8b6101e7178b0343853e1705bf2ef08b3e5a6d` |
| 未修改的内核 ELF | `c3faeded3104bf8c581d2050b5786425b8a7862cea42c1ae19f0e2b98d582af5` |
| SquashFS 镜像，7,688,192 字节 | `62e279ef5795bf546112530e73537495d1d0ef6d87fc4c86d35f8acff0e45da5` |
| 本地 r2 IPK | `433e0f36d867f6934f3f50b9bafd179967dfbb0d30d8e6088d633261d13907a5` |

原内核来自 [ImmortalWrt 24.10 对应架构软件仓库](https://downloads.immortalwrt.org/releases/packages-24.10/aarch64_cortex-a53/packages/)。已校验下载清单；匹配的内核模块来自本机固件发布者保留的 [r0-9a11bb8 软件源](https://kmiit.github.io/Redmi_AX3000_immortalwrt/redmi_ax3000-24.10/r0-9a11bb8/Packages)。没有绕过内核 ABI 依赖检查。

打包工具使用项目维护者提供的 [squashfs-tools-ng Windows 发行包](https://infraroot.at/pub/squashfs/windows/)。本地构建脚本为 [build-sing-box-squashfs-ipk.py](../scripts/build-sing-box-squashfs-ipk.py)，挂载服务与占位入口在 [sing-box-squashfs](../scripts/sing-box-squashfs/) 中。

HomeProxy 另有两项本机调整，由 [patch-homeproxy-init.py](../scripts/patch-homeproxy-init.py) 生成：

- 为代理进程设置 `GOMEMLIMIT=24MiB`、`GOGC=50`。前者是 Go 的软内存目标，不是整个进程的硬上限。
- 清理 TUN 时先检查接口是否存在，避免 Redirect/TPROXY 模式下停止服务返回无意义的失败。

直接升级内核或 HomeProxy 包可能覆盖这些调整。后续升级需复核镜像体积、内核功能、HomeProxy 配置兼容性和补丁；原始完整内核包不能替代本机的压缩挂载包直接安装。

页面加载另有 [RPC 适配补丁](../scripts/patch-homeproxy-rpc.py)，避免查询功能时额外启动第二个 sing-box 进程；原因、匹配条件和验证结果见第 6 节。

## 5. 自动启动与离线行为

本次配置的启动顺序是：

1. `S18sing-box-squashfs` 校验并挂载本地内核。
2. `S99cr8808-proxy-wan` 检查 WAN 是否已获取地址。
3. WAN 尚未就绪时，保留本地 DHCP/DNS，不启动 HomeProxy。
4. 收到 WAN `ifup` 事件时尝试启动 HomeProxy；`ifdown` 时停止代理并恢复普通 DNS。

实现文件：[启动服务](../scripts/cr8808-proxy-wan.init)、[WAN 事件脚本](../scripts/cr8808-proxy-wan.hotplug)。配置开关为 `homeproxy.config.cr8808_autostart=1`。HomeProxy 自身的普通开机入口关闭，由本机的 WAN 条件入口管理。

没有 WAN 时，“HomeProxy 未运行”符合这份配置的预期。目前已观察到 WAN 上线且代理运行；重新断线/上线的自动恢复和受控重启后的恢复仍须后续验收。

## 6. 首次接线后的验收

在 LuCI 中先完成以下检查：

1. **网络 → 接口 → WAN**：应有 DHCP IPv4 地址、网关和 DNS。没有地址时先检查接线和上下游网段。
2. 检查系统时间正常，等待 NTP 校时。本次已修正路由器原先停留在 2026 年 7 月的时间。
3. **服务 → HomeProxy**：确认代理运行、节点可连接；必要时手动启动下面的 WAN 条件服务。
4. 用连接 `HA-NEW` 或 LAN 的终端访问一个直连服务和一个应走代理的服务，核对实际出口；手机测试时关闭移动数据以免误判。
5. 再验证电视、游戏等实际需要的 UDP 应用，以及 NAS、打印机和局域网域名。

**路由器 SSH：**

```sh
ubus call network.interface.wan status
ip -4 route show default
date
/etc/init.d/cr8808-proxy-wan start
/etc/init.d/homeproxy status
nslookup www.baidu.com 127.0.0.1
fw4 check
grep MemAvailable /proc/meminfo
df -h /overlay /tmp
```

WAN 不在线时，上面外网 DNS 查询可能失败，不能据此判断订阅配置有问题。此时先处理 DHCP/上游网络。

本次没有测得代理带宽。电脑连接本机的有线口此前协商为 100 Mbps，测速前需核对实际链路速率，并区分普通转发、直连分流和加密代理吞吐。

### 接线排障：电脑获取了上级设备的网段

2026-10-27 首次接入家庭网络时，电脑实测获得 `192.168.71.14`，DHCP 服务器和网关均为 `192.168.71.1`，原管理地址 `192.168.1.1` 无法访问。用户确认上级设备的网线插在 CR8808 的 **L1（LAN1）**。上游接入 LAN 会让上级 DHCP 直接进入本机 LAN；电脑此时获取的地址不能用来判断 CR8808 自身的管理地址。

处理顺序：

1. 把上级设备出来的网线从 **L1 移到 WAN 口**；电脑、交换机和家庭 AP 接本机 L1/L2/L3 或家庭 Wi-Fi。
2. 电脑重新获取 DHCP 地址。可重插电脑网线，或在 Windows 针对实际有线网卡执行以下命令。本次活动网卡名为 `以太网 3`，其他电脑需替换名称。

   ```powershell
   ipconfig /release "以太网 3"
   ipconfig /renew "以太网 3"
   ```

3. 确认电脑获得 `192.168.1.100`–`192.168.1.249`，网关为 `192.168.1.1`，再打开 `http://192.168.1.1`。
4. 如果仍无法访问，暂时断开 CR8808 的上游线，仅保留电脑直连 LAN，检查链路、地址和管理服务。恢复访问后再检查 WAN 的 DHCP 地址及 HomeProxy 状态。

接线修正后实测：电脑自动获得 `192.168.1.214`，DHCP 服务器、默认网关均为 `192.168.1.1`；管理地址的 HTTP、SSH 端口可连接，首页和普通 RPC 请求可正常返回。有线链路协商为 1 Gbps。电脑通过本机网络访问 `https://www.baidu.com/` 返回 HTTP 200，访问 `https://www.gstatic.com/generate_204` 返回 HTTP 204；这两项验证基本访问，不等同于核对实际代理出口、UDP、性能或启动恢复。

### HomeProxy 一打开页面就出现 `XHR request timed out`

本次实机定位到 `luci.homeproxy.singbox_get_features`：上游实现每次查询都执行 `/usr/bin/sing-box version`。在双频无线和代理已运行、可用内存约 14 MiB 时，额外的版本查询进程占用约 23 MiB RSS，并长时间阻塞 RPC。日志另记录过一次代理内存不足被系统终止，随后由服务管理器重新启动。

已通过 [patch-homeproxy-rpc.py](../scripts/patch-homeproxy-rpc.py) 修补 `/usr/share/rpcd/ucode/luci.homeproxy`，并重启 `rpcd` 加载；本次修复未重启代理核心。补丁使用初次安装时实际取得的 sing-box `1.12.25` 版本和功能输出，并同时检查以下条件：

- `/usr/bin/sing-box` 与 `/tmp/sing-box-squashfs/sing-box` 的设备号、inode、长度一致。
- 长度为 29,688,696 字节，已校验包清单中的 `binary_sha256` 与本手册固定 ELF 哈希一致。
- 满足条件时直接返回该内核的版本和功能，不再启动版本查询进程；内核模块检测沿用原逻辑，其他内核沿用上游查询方式。

修复后，通过真实 HTTP `/ubus/` 请求验证功能查询、UCI 配置读取、主机提示、服务状态、直连域名列表和代理域名列表，六项均返回成功，合并请求约 0.07 秒完成；连续三次功能查询约 0.05–0.06 秒。检查期间未出现额外的版本查询进程，代理核心 PID 保持不变，OOM 计数仍为修复前的一次。用户随后刷新页面，确认 HomeProxy 已正常打开，页面超时问题验收通过；长期负载稳定性仍待验证。

浏览器刷新 HomeProxy 页面即可重新加载；如果管理会话因 `rpcd` 重启失效，重新登录。安装方法见[脚本说明](../scripts/README.md)。回滚时从本次修复前备份提取原始 `usr/share/rpcd/ucode/luci.homeproxy`，恢复该文件后重启 `rpcd`；不要为回滚此项补丁恢复整份网络配置。

## 7. 本次已验证与待验证

| 检查 | 结果 |
| --- | --- |
| 修改前备份下载及 SHA256 | 通过；网络、DHCP、防火墙、无线、shadow 等关键文件存在 |
| 原始软件包、镜像和内核哈希 | 通过；内核 ELF 未修改 |
| 匹配内核模块安装 | 通过，无 `--force-depends` |
| SquashFS 挂载、版本检查、卸载后重新挂载 | 通过 |
| 双频无线运行状态 | 两路均 `up=true`，SSID 和加密配置正确 |
| 节点导入及生成的代理配置检查 | 通过 |
| 离线启动代理、进程环境设置 | 通过 |
| 代理运行期间 `fw4 check` | 通过，`Ruleset passes nftables check` |
| 停止代理后防火墙和 DNS 恢复 | 通过 |
| WAN 未就绪时条件服务不启动代理 | 通过 |
| 预配置短时检查中的 OOM 事件 | 当时为 0；联网后发现 1 次，修复页面查询后的检查未新增 |
| 资源快照 | 持久空间剩余约 4 MiB；离线无线开启时可用内存约 26–33 MiB，联网修复后一次快照约 19 MiB，均随运行状态变化 |
| WAN DHCP | 通过：`192.168.71.18/24`，上级网关 `192.168.71.1` |
| 电脑基本外网访问 | 通过：百度 HTTPS 200、gstatic 检测地址 204；未核对实际代理出口 |
| HomeProxy 页面加载 | 修复后六项 HTTP RPC 均成功，42 个节点仍在；用户确认浏览器页面正常打开 |
| 代理出口核对、UDP 实际连通与性能 | **待验证** |
| 终端实际接入 Wi-Fi、真实断电/重启恢复、持续负载 | **待验证** |

## 8. 停用代理与恢复

临时停用代理，并防止下一次 WAN 上线时重新启动：

**路由器 SSH：**

```sh
uci set homeproxy.config.cr8808_autostart='0'
uci commit homeproxy
/etc/init.d/homeproxy stop
```

恢复 WAN 条件启动：

```sh
uci set homeproxy.config.cr8808_autostart='1'
uci commit homeproxy
/etc/init.d/cr8808-proxy-wan start
```

本次备份和软件包位于电脑项目的 `tmp/router-config/`。其中 `private/` 目录包含 Wi-Fi、订阅和备份凭据，只授权当前 Windows 用户及 SYSTEM 访问，不纳入 Git。

- 修改前：`private/cr8808-before-config-20261027.tar.gz`。
- 配置后：`private/cr8808-configured-20261027.tar.gz`，含网络配置及本机启动脚本。
- 依赖和修正版内核包：`packages/`，使用 **r2** 压缩内核包。
- 测试结果：`evidence/`。
- 恢复包及第二份本地副本的位置、哈希见 `evidence/restore-bundle.json`。
- 本次页面修复前：`private/cr8808-before-xhr-fix-20261027.tar.gz`，含原始 RPC 文件及当时配置，SHA256 为 `76b35d1566d8760f6e0b450ad7558d79b9d63567d5cbcbd0c6ba65b06684327d`。
- 页面修复后：`private/cr8808-xhr-fixed-20261027.tar.gz`，含网络、无线、节点配置、已修补 RPC 文件及本机服务脚本，SHA256 为 `629d821a8669c5cd8341c116237ba0cddcc30d29df16c20d061ce8fabe631ce4`。

恢复包文件名为 `cr8808-main-router-restore-20261027.zip`，主副本在项目的 `tmp/router-config/private/`；第二份位于 `C:\Users\yingj\cr8808-backups\2026-10-27-main-router\`。两份已逐字节校验，均包含配置凭据。

页面修复后另存新恢复包 `cr8808-homeproxy-xhr-fixed-restore-20261027.zip`，同样保存在上述两个目录，包含原有离线软件包、新旧配置快照、RPC 补丁和更新后的手册。新包校验报告为 `evidence/homeproxy-xhr-fix-restore-bundle.json`；需要恢复本次修复后的状态时使用新快照。原恢复包保留用于追溯预配置状态。

修改前备份 SHA256 为 `957786e41834591f4f0d8fd428f1ee7149643c8ebef45b19da17ec4ccb383657`。生成时 `sysupgrade -b` 的引导环境钩子曾提示权限错误；已另外打开归档核对关键配置文件，因此这里把它作为**配置备份**，不作为引导或全分区备份。

若需回到修改前的网络设置，先用上述命令停用代理，再将修改前备份上传到路由器 `/tmp`，核对 SHA256 后恢复配置。恢复到同一台、同一固件环境；软件包恢复则使用保存的离线包，不混装其他内核构建。

Windows 上传使用传统 SCP：

```powershell
scp -O .\tmp\router-config\private\cr8808-before-config-20261027.tar.gz root@192.168.1.1:/tmp/
```

路由器恢复命令（**仅在确实需要回滚时执行**）：

```sh
sha256sum /tmp/cr8808-before-config-20261027.tar.gz
tar -xzf /tmp/cr8808-before-config-20261027.tar.gz -C /
/etc/init.d/network reload
/etc/init.d/dnsmasq restart
/etc/init.d/odhcpd restart
wifi reload
fw4 reload
```

恢复旧网络可能改变管理地址和无线状态，执行前保留有线维护连接。配置归档不包含完整的软件环境；离线恢复包同时保存了所需软件包、脚本和配置，用于在本机匹配固件上重建。
