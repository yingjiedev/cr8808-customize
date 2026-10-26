# CR8808 网页恢复 U-Boot 调研与支持判断

核查日期：2026-10-26。设备依据：2026-10-25 已完成的刷机、备份和重启验证记录。本次只查询资料、下载候选文件并做本地静态检查，未操作路由器，也未刷入第三方 U-Boot。

## 1. 先看结论

**可以实现“按住 Reset 上电，用浏览器上传固件恢复系统”。但当前没有核实到一个能够直接为本机背书、同时保留现有原厂系统槽的现成安装包。**

- **历史 CR880x 网页 U-Boot 文件确实存在。** 已下载固定版本并确认主文件包含网页服务、`192.168.10.1` 和 NAND 驱动字符串；不过它是资源整理包，尚未找到这两个二进制对应的完整源码与构建过程，配套说明还存在冲突。
- **可审查的开源实现也存在。** 优先评估 `1980490718/u-boot-2016`；它有 IPQ5018、公版 MP02.1、网页恢复及交换机相关代码，但核查的配置与发布文件中没有 CR8808/CR880x 专用目标。不能直接拿京东云 AX3000、RAX3000Q 或公版镜像刷本机。
- **“网页恢复”与“合并大分区”应分别决定。** 为取得网页恢复功能，没有必要先放弃原厂槽位。推荐的支持目标是保留原厂分区，增加经过验证的 CR8808 引导配置、双槽位启动和只写指定系统槽的网页恢复。
- **当前支持状态：完成调研和静态检查，可以进入硬件适配验证；尚未形成可给新手执行的 U-Boot 刷入方案。** 本仓库现有刷机脚本仍仅用于原厂系统内安装 OpenWrt，不安装第三方引导。

## 2. 功能怎样实现

```text
上电 → 原有前级引导 → U-Boot（APPSBL）
                       ├─ 检测到恢复按键 → 初始化网口 → HTTP 网页 → 校验并写固件
                       └─ 正常启动 → 加载系统槽内的内核 → ImmortalWrt / 原厂系统
```

网页服务运行在 U-Boot 内，与 LuCI 独立。系统分区不能启动时，只要前级引导、U-Boot、内存和网口初始化正常，就有机会进入网页恢复。[开源实现说明][S1]

“不死”不是损坏保证：U-Boot 自身或前级引导损坏，网页也无法启动。引导阶段检测到固件加载失败可以进入恢复；内核已经取得控制权后的死机，不保证立即自动出现网页，需要另行设计重启/失败计数机制。普通恢复出厂设置也不等于进入网页 U-Boot。

## 3. 本机有什么条件

| 项目 | 已有证据 | 对 U-Boot 适配的意义 |
| --- | --- | --- |
| 原厂身份 | `nvram model=CR8808`、`ap-mp02.1`、`wl_pa_type=xpa` | 按本机板级信息核对，不能仅看外壳或 IPQ5018 字样 |
| 当前系统 | `redmi,ax3000`；ImmortalWrt 24.10-SNAPSHOT；内核 6.6.137 | 现有系统安装、登录和再次重启均通过 |
| NAND | 日志识别 ESMT SPI NAND，128 MiB；页 2048、块 131072、OOB 64 字节 | 有相近驱动基础；完整芯片 ID/具体型号仍需补齐 |
| 网口 | 当前系统驱动 QCA8337 系列交换机；LAN1 已通 | U-Boot 还须独立初始化交换机，系统内通网不能证明引导阶段通网 |
| 主引导 | `mtd11 / 0:APPSBL`，1,310,720 字节 | 最终候选镜像需要符合前级引导要求和分区边界 |
| 备引导 | `mtd12 / 0:APPSBL_1`，同样大小 | 不能假设任意两个文件互为可用救援副本 |
| 分区表 | `mtd1 / 0:MIBIB`，524,288 字节 | 现有物理布局保留；网页功能本身不要求重写它 |
| 系统槽 | `mtd18=rootfs`、`mtd19=rootfs_1`，各 36 MiB | 原厂留在 mtd18，当前 ImmortalWrt 在 mtd19 |
| 备份 | 22 个物理分区、第二份本地 ZIP，已校验 | 可作为恢复材料；不是含 OOB 的编程器全片镜像 |
| 串口 | 原厂环境曾记录 `uart_en=1`、`boot_wait=on` | 本次没有接线验证可中断 U-Boot，不能把变量值当作串口已可用 |

以上来自本项目[实操记录](cr8808-openwrt-hands-on.md)和本地日志。当前固件对应的设备树还给出 Reset GPIO 25、Mesh GPIO 23、交换机复位 GPIO 26、MDIO GPIO 36/37 等线索；这些应在引导环境验证后使用，不能照搬另一型号的 GPIO。

## 4. 找到的项目与实际状态

| 项目 | 2026-10-26 核查结果 | 能否直接用于本机 |
| --- | --- | --- |
| [Lenoud/cr8809-miwifi-openwrt][S2] | 资源整理仓库；仅查到 2026-03-07 的一次源码提交；含三个引导/分区文件。仓库未归档，但这不代表 U-Boot 有持续开发 | **只作为历史候选文件来源**；缺少对应源码、硬件验证和可靠迁移步骤 |
| [1980490718/u-boot-2016][S1] | GPLv2 源码，未归档；最近 Release 为 `main/v2026-10-15`，对应提交 `a677909`；主线提交时间为 2026-09-16（北京时间），2026-10-24 仍有 Issue 更新 | **推荐作为适配基础**；无明确 CR880x 目标，需要板级及双槽位改动 |
| [chenxin527/uboot-qsdk12.5-build][S3] | GPLv2 源码及构建项目；**API 显示已归档**；最后主线提交 2026-08-18；最近 Release 为 `26.08.16-14.22.36-3011049` | 支持表和配置中均未找到 CR880x；可参考网页、DHCP 和构建实现，不能当成本机现成包 |
| [hzyitc/openwrt-redmi-ax3000][S4] | 系统适配项目，安装说明支持沿用原厂 U-Boot，通过原厂 shell 或 UART/TFTP 安装 | **本机已采用这类原厂引导路线**；它提供 OpenWrt 系统适配，不代表附送第三方网页 U-Boot |

维护时间和“未找到目标”的范围限于本次查询的默认分支、配置目录、最近 Release；不据此断言所有论坛附件、其他分支或私有构建都不存在适配。

### 4.1 开源项目已经有哪些基础

`1980490718/u-boot-2016` 已包含：[项目源码][S1]

- IPQ5018 的 NAND、网口、公版 `ipq5018-mp02.1.dts` 和构建配置。
- lwIP HTTP 服务、DHCP、固件上传、分区备份、网页终端等功能。
- 另一个 MP02.1 板级文件中已有 S17C 交换机初始化配置，涉及交换机 GPIO 26 和 MDIO GPIO 36/37，可供核对；其 Reset GPIO 为 33，与本机线索 25 不同，**不能直接使用该型号镜像**。[MP02.1 公版设备树][S5]、[另一 MP02.1 板级配置][S6]
- NAND 表含 `F50D1G41LB(2M)`：ID `c8 11`、128 MiB、2048/131072/64 几何参数。它与本机 ESMT/几何参数有对应线索，但本机完整芯片 ID 还没读到，不能据此直接认定完全匹配。[NAND 驱动][S7]

最关键的缺口是启动与写入策略：当前源码的 NAND UBI 网页升级分支使用 `ROOTFS_NAME0/1/2` 等名称，`ROOTFS_NAME0` 为 `rootfs`，还可选择写入 `rootfs_1`。它**没有按本项目“保留原厂 mtd18，只更新 mtd19”的目标实现隔离**。本次检查的 `cmd_bootqca.c` 也没有小米 `flag_boot_rootfs`、`flag_last_success` 对应处理，需连同其他环境与启动代码一起评估，不能认为公版双系统处理等同于小米双槽位。[网页刷写代码][S8]、[分区名称定义][S9]、[启动代码][S10]

### 4.2 为什么不能通刷“IPQ5018 U-Boot”

同一平台仍有不同的交换机、GPIO、NAND、电源控制、内存布局、设备树选择和前级引导校验。京东云 AX3000 和 Redmi AX3000 的商品名接近，也不等于板级相同。

本机需要最终确认的内容是：**镜像封装能被现有前级接受、ESMT NAND 可靠读写、Reset 能进入网页、至少一个 LAN 口可访问、系统能从 mtd19 启动、上传固件不会覆盖原厂 mtd18。**

## 5. 历史文件包：实际下载与核验

2026-10-26 补充：用户随后提供 `tmp/02-不死引导-WebUBoot/`，三份二进制与本节文件逐字节一致；原始 TXT 的目标分区错误、主/备引导启动标记差异和本机支持判断，见[本地文件包专项核查](cr8808-local-webuboot-review.md)。

文件固定到提交 `52e90d5b08f47f3e5d7519795e0b4d6cdd1cc3a8`，下载目录为本地 `tmp/web-uboot-research/legacy-binaries/`。[固定文件目录][S11]

| 文件 | 字节数 | SHA256 | 本次实际观察 |
| --- | ---: | --- | --- |
| `MIBIB.bin` | 524288 | `c56efb1b07051d2c799b20cec147ac5ba672a72c5bad4529ec7de865ac54becd` | 与本机原厂 mtd1 备份逐字节相同 |
| `APPSBL.bin` | 1310720 | `a92f08878499bb697e67cfb5f597bb5757e48b4846f4f250fbc612ea166ad4f3` | ELF；含网页内容、`ipaddr=192.168.10.1`；版本字符串 `U-Boot 2016.01 (Dec 14 2022 - 10:32:35 +0800)` |
| `APPSBL1.bin` | 1310720 | `c399dcae6af94e8067532c64f3bc7b137169fbbe80b539f952d9c468fa075cb5` | ELF；与主文件不同；版本字符串为 2021-12-09，默认地址字符串为 `192.168.31.100` |

这些 SHA256 是本次本地计算值，便于复现同一份文件；**不是原作者签名，也不是适配认证**。2026 年提交到资源仓库，不代表引导程序在 2026 年重新开发或修复过。

### 5.1 “合并分区”名称与文件内容不一致

解析下载包 `MIBIB.bin` 的 Qualcomm 分区表，结果仍为 22 个分区，末尾是：

```text
名称       起始偏移     大小         MiB
rootfs     0x00a80000   0x02400000   36
rootfs_1   0x02e80000   0x02400000   36
overlay    0x05280000   0x01f00000   31
data       0x07180000   0x00d80000   13.5
```

这与本机原厂布局相同。**单独刷这个 MIBIB 文件不会让本机获得更大的系统分区。** 如果这份旧 U-Boot 实际提供大分区，仍需查清其是否在运行时修改 SMEM、分区信息或内核参数，以及网页写入的边界。本次没有对应源码或实机引导日志，不能把具体合并方式和可用容量当作已确认事实。

### 5.2 配套说明有哪些问题

资源仓库[主 README][S12]与[目录内操作文档][S13]不能直接拼成安装手册：

- 把 Linux 的 `cat /proc/mtd`、`mtd write` 与 U-Boot 的 `tftpboot`、`flash` 混在同一执行环境里；原厂 U-Boot 通常不是 Linux shell。
- 示例分区表与本机不一致；目录内文档一处把 `APPSBL1.bin` 文件名用作 `flash` 的目标分区名，本机实际分区名称是 `0:APPSBL_1`。
- 对修改分区表后何时断电、重启的描述不能形成可验证的完整迁移流程。
- 文档称更换后串口会被禁用；这尚未在本机验证，但说明不能先假定“换完还一定能串口救援”。
- 主、备文件的版本、地址和内容均不同，不能仅凭文件名认定二者具备等价的网页恢复能力。

因此可以继续研究二进制，但目前不提供把它们直接写入本机 mtd1/mtd11/mtd12 的复制粘贴命令。

## 6. 推荐怎样支持本机

### 路线 A：保留分区，新增 CR8808 开源适配（优先）

这是“增加网页救援，同时保留官方系统”的推荐方向。需要完成以下工作，**不是现成安装步骤**：

| 顺序 | 需要完成的工作 | 通过条件 |
| --- | --- | --- |
| 1 | 补齐 UART 实测日志、CDT/machid、完整 NAND ID、前级引导/封装要求；更新当前配置备份 | 串口能读取并中断原厂引导；本机备份可读且有第二份；明确可用的救援入口 |
| 2 | 在固定源码上新增 `ipq5018_cr8808_defconfig` 与专用 DTS/设备树选择项 | 从本机 MP02.1/QCA8337 拓扑核对 Reset、LED、NAND、MDIO、交换机配置；不复用其他型号产物 |
| 3 | 实现当前槽位选择与小米启动变量兼容，加载正确的 FIT 配置和 UBI kernel 卷 | 能从 mtd19 的既有系统启动，启动参数仍为 `ubi.mtd=rootfs_1`；能明确选择原厂 mtd18 |
| 4 | 修改网页固件写入路径与限制 | 默认只更新 mtd19，限制在 36 MiB 内并处理坏块；拒绝未知格式；失败时不改启动选择 |
| 5 | 禁止普通恢复流程覆盖 mtd18、引导链、分区表、ART、bdata；协调系统内升级逻辑 | 页面和系统升级均不会因“另一槽位”策略误覆盖保留的原厂系统 |
| 6 | 用确认适合该板的加载/验证方法试运行，再制定持久化安装方式 | 先验证按键、网口、HTTP、NAND读取和正常启动；不能假定所有 `.mbn` 可用 `go` 直接试跑 |
| 7 | 完成持久化安装及恢复验证 | 冷启动、Reset 进入网页、正常启动、重装匹配 factory UBI、启动槽保持、原厂槽与关键分区校验均通过 |

固件镜像也要配套核对：当前安装文件为 17,694,720 字节的 factory UBI，尺寸小于 36 MiB，但“放得下”只证明容量满足条件，不证明第三方 U-Boot 的加载地址、FIT 配置和启动参数兼容。

本机现有 ImmortalWrt 的升级代码会写另一个系统槽。从当前 mtd19 执行原版升级流程，会以 mtd18 为目标；若长期保留原厂系统，**必须同时修改升级策略或明确限制升级方式**，不能只在网页里保护原厂槽。[本次系统升级代码][S14]

### 路线 B：继续验证历史网页 U-Boot 文件包

可能减少开发量，但需要先找到对应源码或同主板、同 NAND、同引导版本的可信验证记录，并查明实际分区与串口行为。现有静态结果不足以决定只换主引导、同时换双份引导，或更改分区表。

如果最终选择合并系统空间，应将其视为一次独立布局迁移：原厂双槽位切换恢复方法可能失效，当前系统也可能需要重装；回原厂需要恢复原布局、匹配的引导及本机系统/数据备份。不能承诺仍可简单切回官方。

### 路线 C：继续保留原厂 U-Boot

这是当前已验证设备状态。继续使用 ImmortalWrt，并完善原厂切槽、UART/TFTP 救援材料；无需为正常使用系统立即更换引导。此路线没有新增网页 U-Boot 功能。

## 7. 新手现在可以执行的检查

以下只读取信息，不会安装 U-Boot。电脑 PowerShell：

```powershell
ssh root@192.168.1.1
```

进入路由器 SSH 后：

```sh
ubus call system board
cat /proc/cmdline
cat /proc/mtd
dmesg | grep -Ei 'spi-nand|nand.*found|block size|page size|OOB'
sha256sum /dev/mtd1 /dev/mtd11 /dev/mtd12 /dev/mtd18
fw_printenv flag_boot_rootfs flag_last_success
```

大致返回和判断：

| 输出 | 判断 |
| --- | --- |
| `board_name: redmi,ax3000`，启动参数含 `ubi.mtd=rootfs_1` | 符合本次安装后的系统与槽位 |
| `mtd18: 02400000 ... "rootfs"`，`mtd19: 02400000 ... "rootfs_1"` | 仍是本项目原厂双槽位布局 |
| `ESMT SPI NAND was found`、`128 MiB`、`2048`、`64` | 与已记录 NAND 线索相符；还不是完整芯片 ID |
| mtd1/mtd11/mtd18 的哈希与本机原厂备份相同 | 这些内容仍保留；mtd12 也应与自己的备份单独比较 |
| 启动标记为 `1` | 与当前 mtd19 启动方向相符；仍以实际 cmdline 为准 |
| 缺字段、布局改变、CRC 错误或哈希不符 | 先重新核对当前状态，不能直接套用本报告的原厂布局推论 |

读取 NAND 哈希可能耗时，应等待命令结束。当前系统内这些检查通过，仍然不能替代串口和第三方引导的实际验证。

## 8. 本次交付与下一步边界

已完成：项目维护状态核查、候选配置和关键源码阅读、历史三文件下载及 SHA256 计算、与本机原厂备份比较、MIBIB 分区表解析、支持路线判断。

尚未完成：第三方 U-Boot 编译、CR8808 板级适配、上电串口测试、候选引导运行、网页刷机及冷启动验证。**本机仍保留原厂 U-Boot，当前 ImmortalWrt 和原厂系统槽未因本次调研改变。**

后续若实施，优先做“串口和硬件参数确认 → 开源 CR8808 专用配置 → 保留双槽位的网页恢复验证”，再决定是否另行扩容。不能把本调研的候选文件表理解为已批准使用的刷写清单。

中间资料位于 `tmp/web-uboot-research/`，包括原始下载、`binary-inspection.json`、`mibib-partitions.json` 和 `sources/`，受 Git 忽略。后续按用户要求整理的[历史候选包](../firmware/webuboot/cr880x-20221214/README.md)另存于项目 `firmware/webuboot/`，随文档提交；二进制未修改，仍未通过本机启动验证。

## 来源

优先引用项目源码、发布信息和原始安装说明。旧资源包仅用作证明“文件中有什么”，没有把其适配声明当作本机验证结果。仓库状态和 Release 日期另由 GitHub API 核对，原始响应保存在本地 `sources/`。

- [S1：1980490718 固定版本说明][S1]、[对应 Release][S15]、[仓库状态 API][S16]
- [S2：历史资源整理仓库][S2]、[固定三文件目录][S11]
- [S3：uBootKit 固定版本说明][S3]、[对应 Release][S17]、[仓库状态 API][S18]
- [S4：原厂引导下的系统安装说明][S4]
- [S5：公版 MP02.1][S5]、[S6：另一 MP02.1 板级配置][S6]、[S7：NAND 驱动][S7]
- [S8：网页刷写][S8]、[S9：目标分区名称][S9]、[S10：启动实现][S10]
- [S12：旧包主说明][S12]、[S13：旧包目录说明][S13]
- [S14：当前系统的双槽位升级实现][S14]

[S1]: https://github.com/1980490718/u-boot-2016/blob/a67790948d0b6e0fc68e3bebf268b3a6f5c12bba/README.md
[S2]: https://github.com/Lenoud/cr8809-miwifi-openwrt
[S3]: https://github.com/chenxin527/uboot-qsdk12.5-build/blob/9ce315735ac88fd0a7c7697bc527a8616ed0a972/README.md
[S4]: https://github.com/hzyitc/openwrt-redmi-ax3000#how-to-install
[S5]: https://github.com/1980490718/u-boot-2016/blob/a67790948d0b6e0fc68e3bebf268b3a6f5c12bba/arch/arm/dts/ipq5018-mp02.1.dts
[S6]: https://github.com/1980490718/u-boot-2016/blob/a67790948d0b6e0fc68e3bebf268b3a6f5c12bba/arch/arm/dts/ipq5018-ruijie-ma3063-mp02.1.dts
[S7]: https://github.com/1980490718/u-boot-2016/blob/a67790948d0b6e0fc68e3bebf268b3a6f5c12bba/drivers/mtd/nand/qpic_nand.c
[S8]: https://github.com/1980490718/u-boot-2016/blob/a67790948d0b6e0fc68e3bebf268b3a6f5c12bba/net/httpd.c
[S9]: https://github.com/1980490718/u-boot-2016/blob/a67790948d0b6e0fc68e3bebf268b3a6f5c12bba/include/ipq_api.h
[S10]: https://github.com/1980490718/u-boot-2016/blob/a67790948d0b6e0fc68e3bebf268b3a6f5c12bba/board/qca/arm/common/cmd_bootqca.c
[S11]: https://github.com/Lenoud/cr8809-miwifi-openwrt/tree/52e90d5b08f47f3e5d7519795e0b4d6cdd1cc3a8/CR880X%E5%90%88%E5%B9%B6%E5%88%86%E5%8C%BA%E5%B9%B6%E5%88%B7%E5%B8%A6web%E7%9A%84uboot
[S12]: https://github.com/Lenoud/cr8809-miwifi-openwrt/blob/52e90d5b08f47f3e5d7519795e0b4d6cdd1cc3a8/README.md
[S13]: https://github.com/Lenoud/cr8809-miwifi-openwrt/blob/52e90d5b08f47f3e5d7519795e0b4d6cdd1cc3a8/CR880X%E5%90%88%E5%B9%B6%E5%88%86%E5%8C%BA%E5%B9%B6%E5%88%B7%E5%B8%A6web%E7%9A%84uboot/cr880x%E5%90%88%E5%B9%B6%E5%88%86%E5%8C%BA%E5%88%B7%E5%85%A5%E4%B8%8D%E6%AD%BB.md
[S14]: https://github.com/kmiit/Redmi_AX3000_immortalwrt/blob/9a11bb83d22efd5879439427cd222b957f6f7019/target/linux/qualcommax/ipq50xx/base-files/lib/upgrade/mi_dualboot.sh
[S15]: https://github.com/1980490718/u-boot-2016/releases/tag/main%2Fv2026-10-15
[S16]: https://api.github.com/repos/1980490718/u-boot-2016
[S17]: https://github.com/chenxin527/uboot-qsdk12.5-build/releases/tag/26.08.16-14.22.36-3011049
[S18]: https://api.github.com/repos/chenxin527/uboot-qsdk12.5-build
