# CR8808 刷入 OpenWrt 调研与操作路线

按步骤执行请看[刷机实操手册](cr8808-openwrt-hands-on.md)。

首次操作从[Windows 新手完整教程](cr8808-beginner-guide.md)开始，本文用于查阅来源、其他硬件分流和恢复边界。

调研日期：2026-10-25（Asia/Shanghai）。本文是基于公开源码、作者发布页和原始实机反馈的初次调研记录，该阶段没有连接路由器或执行刷写。后续已完成实机 root、备份和指定 ImmortalWrt 镜像安装，详见上方实操记录；下文保留按硬件分流的调研依据。

后续实机结果：`ap-mp02.1`、原厂 `mtd18/mtd19` 布局、`wl_pa_type=xpa`；安装 `ci-redmi_ax3000-24.10-20260716-145815-UTC` 的 `redmi_ax3000` factory UBI 后，实际启动为 `ImmortalWrt 24.10-SNAPSHOT r0-9a11bb8 / Linux 6.6.137`。有线、管理员登录、再次重启和原厂槽位哈希检查通过；两路无线已识别但暂关闭，WAN/吞吐/断电冷启动未测试。该社区仓库已归档，Release 标为预发布，本次结果不能推断为持续维护承诺。

## 1. 结论与推荐路线

**CR8808 有可核查的 OpenWrt 社区适配与刷写路径。应先确认硬件，再获得 root 访问、备份分区，最后把匹配的 factory UBI 镜像写入未运行的系统槽位。首次尝试建议保留原厂 U-Boot 和分区表。** 适配作者同时给出了原厂系统内刷写和 UART/U-Boot 刷写两条路径。[适配项目安装说明][S1]

需要区分三个事实：

- **社区支持与官方镜像是两回事。** 本次核查 OpenWrt 官方 `25.12.6` 和 snapshot 的 `qualcommax/ipq50xx/profiles.json`，分别有 5、27 个 profile，均未找到 CR880x、CR881x 或 Redmi AX3000；官方 `main` 的 IPQ50xx 镜像定义也未找到对应设备。不能给 CR8808 随意选一个同芯片官方固件。[稳定版清单][S2]、[snapshot 清单][S3]、[官方源码][S4]
- **CR8808 标签不足以选包。** 原始实机记录包含 M81/IPQ5000、M79/IPQ5000 和 M79/IPQ5018 三类；后者需要核对 CR881x 设备定义。[实机记录 Issue #75][S5]
- **能启动与适合长期使用是两回事。** 旧 QSDK 分支有 NSS 加速支持，但 OpenWrt 21.02 官方分支早已结束维护；较新的社区分支也必须独立核查驱动、更新与实机兼容性。[QSDK 分支能力表][S6]、[官方停止维护公告][S7]

本项目当前建议：**先确认硬件；能通过 XMiR-Patcher 获得 root 时，优先走原厂分区方案；不能获得 root 时，再考虑作者记录的 UART/TFTP 方案。暂不把“合并大分区、换 Web U-Boot”作为默认步骤。** 这是依据写入范围和恢复条件作出的工程选择，并非所有硬件都已由本项目验证。

## 2. 先确认这台 CR8808 属于哪类

### 2.1 硬件与目标的对应关系

| 实机线索 | 社区常见叫法 | 源码中对应的候选目标 | 判定要求 |
| --- | --- | --- | --- |
| M81、IPQ5000 的旧版 CR880x | 通常归为 A 版 | `redmi_ax3000` | 确认原始型号、主板与分区布局 |
| M79、IPQ5000 的旧版 CR880x | 通常归为 A 版 | `redmi_ax3000` | 不能因为 M79 就改选 CR881x |
| M79、IPQ5018 的后期硬件，原厂环境型号可能为 CR881x | 常被称为 B 版或 CR881x | `xiaomi_cr881x` | 还要检查 NAND 型号及具体批次支持情况 |
| 已刷第三方引导或已合并分区 | 不能单靠 A/B 分类 | 取决于现有布局 | 本文双槽位命令不能直接套用 |

对应关系来自 [Issue #75 的实机记录][S5]，以及适配项目将 `redmi_ax3000` 和 `xiaomi_cr881x` 分开的[镜像定义][S8]。A/B 是社区叫法，执行时应以主板、原始设备信息、闪存和目标定义交叉确认。

特别注意：

1. **M79 同时存在不同 SoC 的版本。** 生产日期只能辅助判断，不能作为唯一依据。
2. **U-Boot 显示 `IPQ5018#` 也不足以认定为 B 版。** 原始记录明确指出两类机器都可能显示这个提示符；旧版 AX3000 的 DTS 本身也使用 IPQ5018 公共定义。[实机记录][S5]、[AX3000 DTS][S9]
3. 串口位置可以辅助辨认，Issue #75 有相应说明，但观察方向、PCB 版本不同会造成误判；应对照原图和主板标识。
4. 已经跨型号刷过原厂系统的机器，后台显示的型号可能不再反映原始硬件。

### 2.2 获取 root 后，先收集这些信息

以下在**路由器 Linux shell** 中执行，属于只读采集；某些路径或命令不存在时记录现象即可：

```sh
cat /proc/mtd
cat /proc/cmdline
cat /sys/class/ubi/ubi*/mtd_num
cat /tmp/sysinfo/board_name 2>/dev/null
cat /proc/device-tree/model 2>/dev/null
nvram get model
nvram get flag_boot_rootfs
nvram get flag_last_success
nvram get flag_try_sys1_failed
nvram get flag_try_sys2_failed
dmesg | grep -Ei 'nand|spi|qpic|ipq|machine|memory'
df -h /tmp
free
```

将结果保存到电脑的 `tmp/device-info/`，并记录底部标签、原厂版本号、PCB 丝印、NAND 型号、网口连接和串口照片。涉及序列号、MAC、密钥的实机输出留在本地即可。

**进入刷写阶段的最低条件：** 已确认目标、原厂引导是否保留、分区表、当前槽位、NAND 支持和可用备份。若仍只有“CR8808/M79”这些信息，继续采集，暂不选定镜像。

## 3. 固件来源与镜像类型

### 3.1 本次核查的候选项目

| 来源 | 核查结果 | 适用价值与限制 |
| --- | --- | --- |
| `hzyitc/openwrt-redmi-ax3000`，QSDK 5.4 / OpenWrt 21.02 分支 | README 列 CR880x、CR881x 的启动、交换机、无线及 NSS NAT 支持；本次发布列表中最新条目日期为 2024-07-27 | 适合研究已有刷写路径和 NSS；21.02 官方已 EOL，不能把“作者称稳定”理解成仍有官方安全维护 |
| 同项目，mainline kernel 5.15 / OpenWrt 23.05 开发分支 | README 列出的 NSS NAT 为不支持，无线无 NSS Offload | 这里的 mainline 指该分支的内核路线，不代表 CR8808 已进入 OpenWrt 官方发布；不能承诺千兆路由吞吐 |
| `kmiit/Redmi_AX3000_immortalwrt` | 本次最新发布条目为 `ci-redmi_ax3000-24.10-20260716-145815-UTC`，提供 factory 与 sysupgrade；README 沿用 hzyitc 安装说明。仓库已归档，Release 为预发布 | 本机已完成此版本的基础安装验证；已查的设备定义仅列 `redmi_ax3000`、`cmcc_rax3000q`，不能外推支持 CR881x 或持续维护 |

来源：[hzyitc 主分支说明][S1]、[QSDK 5.4 说明][S6]、[发布列表][S10]、[kmiit README][S11]、[kmiit 发布][S12]、[kmiit 设备定义][S13]。

选择建议：先用硬件排除不匹配的目标；再根据 NSS、软件源可用性、补丁维护和实机报告选择分支。较新的发布日期不自动证明无线性能、NAND 支持或安全补丁完整。

### 3.2 文件类型不能混用

| 文件类型 | 典型用途 | 本项目的使用原则 |
| --- | --- | --- |
| 小米 `miwifi_...bin` | 原厂升级、原厂 TFTP 恢复 | 必须匹配实际硬件与原厂恢复机制 |
| `...factory.ubi` / `...nand-factory.ubi` | 本文社区方案的首次安装 UBI 镜像 | 通过该项目支持的原厂 shell 或 U-Boot 路径写入，不视为小米后台能直接接受的包 |
| `...initramfs...itb` | 按项目说明从 RAM 启动、诊断 | 不代替 factory UBI，不直接按本文命令写入 rootfs |
| `...sysupgrade.bin` | 已运行匹配系统后的升级 | 要有当前平台的升级支持；不能据扩展名跨分支、跨目标升级 |
| `MIBIB`、`APPSBL`、`APPSBL_1` 等备份/镜像 | 分区表和引导链 | 原厂分区路线不写这些文件；第三方大分区包需要另行成套核查 |

hzyitc 已查镜像定义将这两个目标的输出限制为 `nand-factory.ubi`；不能假设它也支持通用 sysupgrade。kmiit 提供 sysupgrade，并有 `redmi,ax3000` 的专用双启动升级逻辑。[hzyitc 镜像定义][S8]、[kmiit 升级代码][S14]

### 3.3 可复查的版本、文件与 SHA256

以下是**发布者给出的预期值**，本次没有下载固件做内容校验。实际刷写前仍须下载、核对哈希并确认目标。

**历史 QSDK 5.4 基线：** [2024-07-27 固定 Release][S15]，标签为：

```text
ci-ipq50xx-qsdk-kernel-5.4-openwrt-21.02-qsdk-11.5.05.841.1029-20240727-173350-UTC
```

| 目标 | 完整文件名 | SHA256 |
| --- | --- | --- |
| 旧版 CR880x / IPQ5000 候选 | `openwrt-ipq50xx-arm-redmi_ax3000-squashfs-nand-factory.ubi` | `8ec4fd5b5c2ad4d7f802ad57f356811216b75f032103c7662879aca985be9f3e` |
| CR881x / IPQ5018 候选 | `openwrt-ipq50xx-arm-xiaomi_cr881x-squashfs-nand-factory.ubi` | `2901467ffeb050876145dbf67a1138891ee146f5bac69aa58d35afa07f0f726d` |

**较新 ImmortalWrt 候选：** [2026-07-16 固定 Release][S12]。

| 用途 | 完整文件名 | SHA256 |
| --- | --- | --- |
| 首次安装 | `immortalwrt-qualcommax-ipq50xx-redmi_ax3000-squashfs-factory.ubi` | `897fd05dd6584e820aeb99905191dd8532564758c12db486e8041625d00797e7` |
| 匹配系统内升级 | `immortalwrt-qualcommax-ipq50xx-redmi_ax3000-squashfs-sysupgrade.bin` | `bbd385217b4c07b374bfbcf6f324c2c162a58038bf9f33482d13a6f05eb8efd5` |

不要把这些值用于其他标签的同名文件。固定 Release 和同版本 `sha256sums` 比 `latest/download` 更便于追溯；哈希能检查文件是否一致，不能替代对发布者和构建来源的判断。

## 4. 路线一：取得 root，保留原厂分区刷入

### 4.1 准备与获得访问权限

准备有线电脑、稳定电源、网线、匹配的恢复固件，以及足够保存全部备份的磁盘空间。电脑连接路由器 LAN 口；原厂后台常用 `192.168.31.1`，以实机地址为准。调试时避免同时接入会造成地址冲突的网络。

XMiR-Patcher 使用当前作者仓库 [openwrt-xiaomi/xmir-patcher][S16]；旧链接、网盘打包版本不作为默认来源。在电脑项目根目录执行以下准备命令会把工具也放进忽略目录：

```powershell
git clone https://github.com/openwrt-xiaomi/xmir-patcher.git .\tmp\xmir-patcher
Set-Location .\tmp\xmir-patcher
.\run.bat
```

按本次核查的[主菜单源码][S17]：

1. `1 - Set IP-address`：填写实际路由器地址。
2. `2 - Connect to device (install exploit)`：按提示提供本机管理信息，尝试获取访问权限。
3. `3 - Read full device info`：读设备和分区信息，回到第 2 节确认目标。
4. `4 - Create full backup`：完成备份并验证。
5. `6 - Install permanent SSH` 是额外的持久化修改，按需选择；它不是已经获得 root 后手工刷写的必需步骤。

菜单 `7` 是固件安装入口，扩展菜单还有引导安装功能。**本文采用手工核对分区的流程；不要把能运行工具理解为任意固件或引导都兼容。** 新原厂固件可能堵住工具利用的入口；获取权限失败时先记录固件版本和工具错误，不连续尝试不明降级包。

原始实测还记录了原厂后台 `set_telnet?enable=1` 入口，适用范围取决于原厂版本，不能保证所有设备可用，也不能由返回成功推断已获得 root。[Issue #75][S5]

### 4.2 备份与核验

XMiR-Patcher 的备份代码把文件下载到工具目录的 `backups/`，并分块读取路由器 MTD；将工具放在项目 `tmp/` 后，这些文件自然在 Git 忽略范围内。[备份源码][S18]

应保存完整的 MTD 分区集、分区表、原始设备信息、启动日志和启动变量，特别核对下列内容；具体名称及编号以实机为准：

| 内容 | 用途 |
| --- | --- |
| `MIBIB`、启动链分区、`APPSBL` 及其副本 | 记录原始布局与引导，供专门的恢复方案使用 |
| `ART` / 无线校准相关分区 | 保留本机射频校准数据 |
| `bdata`、环境变量、配置相关分区 | 保存型号、MAC、序列号和启动状态等本机信息 |
| `rootfs`、`rootfs_1` | 保留原厂系统内容和双槽位恢复依据 |

电脑侧检查每个备份的文件长度与分区信息相符，并对文件计算 SHA256；不能仅看到“备份完成”就继续。PowerShell 示例（从项目根目录）：

```powershell
Get-ChildItem .\tmp\xmir-patcher\backups\*.bin | Get-FileHash -Algorithm SHA256
```

再把备份复制到第二个存储位置。工具的分区读取备份**不等于包含 OOB、坏块等物理信息的编程器全片镜像**；恢复 NAND 时仍须采用匹配的工具和布局。不要把别人机器的校准、身份分区用于本机。

路由器 `/tmp` 通常使用内存；不能把全部分区先堆在路由器 `/tmp` 再一次性取走。XMiR 的分块下载可减少这种占用。[备份实现][S18]

### 4.3 下载并传入匹配的 factory UBI

从电脑的项目根目录执行，保存到 `tmp/firmware/`，使用固定 Release。下面仅演示**已确认旧版 CR880x/IPQ5000** 时，下载第 3.3 节历史基线并核对发布哈希；这不是对其长期公网部署的推荐：

```powershell
New-Item -ItemType Directory -Force .\tmp\firmware | Out-Null
$firmwareFile = '.\tmp\firmware\openwrt-ipq50xx-arm-redmi_ax3000-squashfs-nand-factory.ubi'
$firmwareUrl = 'https://github.com/hzyitc/openwrt-redmi-ax3000/releases/download/ci-ipq50xx-qsdk-kernel-5.4-openwrt-21.02-qsdk-11.5.05.841.1029-20240727-173350-UTC/openwrt-ipq50xx-arm-redmi_ax3000-squashfs-nand-factory.ubi'
Invoke-WebRequest -Uri $firmwareUrl -OutFile $firmwareFile
$expectedHash = '8ec4fd5b5c2ad4d7f802ad57f356811216b75f032103c7662879aca985be9f3e'
if ((Get-FileHash -LiteralPath $firmwareFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) { throw '固件 SHA256 不匹配，停止。' }
scp -O $firmwareFile root@192.168.31.1:/tmp/
```

地址和登录方式以已确认的实机为准。`scp -O` 使用旧 SCP 协议，适用于没有 SFTP 子系统的原厂 Dropbear；若客户端不支持该选项，使用匹配的 SCP 客户端。传输后还要在路由器上再次校验文件。

**电脑的项目 `tmp/` 与路由器的 `/tmp/` 是两个不同目录。** 前者保存研究和备份，后者只是此次刷写的临时输入位置。

### 4.4 确认当前槽位，只写另一槽

作者安装说明的示例要求 `rootfs=mtd18`、`rootfs_1=mtd19`，并根据 `/proc/cmdline` 的 `ubi.mtd=` 选择另一槽位。[原始安装说明][S1]

后续实机发现原厂 `6.2.33` 没有 `sha256sum`，可使用 `openssl dgst -sha256`；下方研究示例会因工具缺失而停止，不应绕过校验。实际命令与当前完成范围以[实操记录](cr8808-openwrt-hands-on.md)为准。

| 当前运行槽位 | 待写入设备 | 新的 `flag_boot_rootfs` / `flag_last_success` | 清零的失败标记 |
| --- | --- | --- | --- |
| `rootfs`（mtd18） | `/dev/mtd19`，即 `rootfs_1` | `1` | `flag_try_sys2_failed` |
| `rootfs_1`（mtd19） | `/dev/mtd18`，即 `rootfs` | `0` | `flag_try_sys1_failed` |

以下脚本根据作者流程补充了失败退出、哈希检查和目标 UBI 附着检查。**它仅演示第 3.3 节指定的旧版 CR880x/IPQ5000 镜像及上述原厂布局；不适用于硬件未确认、CR881x、合并分区、已更换引导或其他固件版本。脚本不会自动识别硬件，必须先完成第 2 节确认与备份。**

在路由器原厂 Linux 的 root shell 中执行：

```sh
set -eu

IMAGE=/tmp/openwrt-ipq50xx-arm-redmi_ax3000-squashfs-nand-factory.ubi
EXPECTED=8ec4fd5b5c2ad4d7f802ad57f356811216b75f032103c7662879aca985be9f3e

for cmd in ubiformat nvram sha256sum; do
    command -v "$cmd" >/dev/null || exit 1
done
[ -s "$IMAGE" ] || exit 1
printf '%s  %s\n' "$EXPECTED" "$IMAGE" | sha256sum -c - || exit 1

[ "$(awk '$4 == "\"rootfs\"" {print $1}' /proc/mtd)" = 'mtd18:' ] || exit 1
[ "$(awk '$4 == "\"rootfs_1\"" {print $1}' /proc/mtd)" = 'mtd19:' ] || exit 1

SLOT=$(sed -n 's/.*ubi\.mtd=\([^ ]*\).*/\1/p' /proc/cmdline)
case "$SLOT" in
    rootfs)
        TARGET=/dev/mtd19
        TARGET_NUM=19
        NEW_SLOT=1
        FAILED_FLAG=flag_try_sys2_failed
        ;;
    rootfs_1)
        TARGET=/dev/mtd18
        TARGET_NUM=18
        NEW_SLOT=0
        FAILED_FLAG=flag_try_sys1_failed
        ;;
    *)
        echo '当前槽位无法按本文识别，停止。'
        exit 1
        ;;
esac

# 目标若已经附着为 UBI，停止，避免格式化正在使用的分区。
for entry in /sys/class/ubi/ubi[0-9]*/mtd_num; do
    [ -f "$entry" ] || continue
    if [ "$(cat "$entry")" = "$TARGET_NUM" ]; then
        echo '目标分区已附着为 UBI，停止。'
        exit 1
    fi
done

echo "当前槽位=$SLOT；即将格式化并写入 $TARGET"
# 保留 ubiformat 的交互确认；写入失败时不改变启动标记。
ubiformat "$TARGET" -f "$IMAGE" || exit 1
nvram set "$FAILED_FLAG=0"
nvram set "flag_boot_rootfs=$NEW_SLOT"
nvram set "flag_last_success=$NEW_SLOT"
nvram commit
sync
echo '写入完成。核对输出无错误后，再单独执行 reboot。'
```

确认写入、变量提交均无错误，再执行 `reboot`。没有输出“写入完成”时，保存完整日志；不要继续重启或绕过检查。

上述检查故意在布局、槽位表达形式或工具不符时停止。若 `/proc/cmdline` 使用数字而非分区名，先与实际 UBI 附着关系核对，不能直接删掉检测。保留原厂另一槽位能提供恢复机会，但不保证不会触发原厂自动回滚机制。

### 4.5 CR881x / 后期硬件如何处理

流程仍是“确认目标 → root → 备份 → 匹配 factory UBI → 按实际布局写入”，但应单独执行以下核查：

1. 目标应与 `xiaomi_cr881x` 定义一致，不能只替换第 4.4 节脚本里的文件名就刷。
2. 检查 NAND 支持。Issue #89 中，有用户在正确 CR881x 目标下仍因 `GD5F1GM7REYIG` 闪存支持缺失而无法启动，补丁后才成功；这不能推出旧 Release 已包含该补丁。[原始反馈和讨论][S19]
3. 检查冷启动网口和自动回滚问题。Issue #89 有回滚反馈；Issue #150 有特定 CR881x 主板冷启动时交换机探测失败的反馈。[Issue #89][S19]、[Issue #150][S20]
4. 若 Release 不包含所需 NAND/主板修复，应选明确包含补丁且有同硬件验证的构建，或从可审查的源码自行构建。当前用户实机信息不足，无法确定需要哪种补丁。

讨论中存在覆盖两个 rootfs 来避免回滚的做法，但这会失去保留的原厂系统槽位。本文不把它当作首次刷机的默认操作，也不把某条 Issue 已关闭理解为所有历史镜像均已修复。

## 5. 路线二：UART + 原厂 U-Boot + TFTP

适用条件：硬件已确认，软件入口不可用或需要串口诊断，且保留了原厂引导和匹配的分区布局。作者 README 记录先进行一次匹配原厂固件的 TFTP 恢复，以允许 UART 输入，再中断 U-Boot。[作者 UART 安装流程][S1]

### 5.1 串口与原厂恢复

- 按实机主板识别 GND、TX、RX；USB-TTL 的 TX 接路由器 RX，RX 接路由器 TX，共地，**不连接 VCC**。
- 原始 CR8808 实机报告使用 115200 波特率；设备树为 `115200n8`。接口电平和焊点须按实际 PCB 核实，不能将 5V 或 RS-232 电平直接接入。[实机接线报告][S21]、[设备树][S9]
- 电脑有线连接 LAN1，使用小米修复工具及与硬件匹配的原厂包；按作者流程按住 Reset 上电，观察工具和串口日志，等待恢复完成后再按提示重启。
- 小米修复工具本质上参与 DHCP/TFTP 恢复。它使用原厂包，不是通用 OpenWrt UBI 上传器。恢复阶段的网络设置与随后手工 TFTP 的设置分别核对。

本次可达性核查（HTTP HEAD，未下载运行）：

| 资源 | 结果与限制 |
| --- | --- |
| [小米修复工具][S22] | HTTP 200；`Content-Length=979690` |
| [CR8808 历史原厂 6.2.11][S23] | HTTP 200；`Content-Length=27788308`；作者列出的旧型号恢复包，不据此推断兼容后期 B 版/CR881x |
| 第 3.3 节红米 QSDK 5.4 factory UBI | HTTP 200；`Content-Length=11927552`；仍待实际下载校验 |

来源入口：[小米官方下载页][S24]、[作者机型与原厂包对应表][S1]。不能因为网上有 CR8808 改刷 CR8806 的经验，就把跨型号原厂包作为所有机器都必需的前置步骤。

恢复后在串口中断启动，作者给出的 UART 开启命令为：

```text
setenv boot_wait on
setenv uart_en 1
saveenv
```

先保存启动环境和分区信息，完成能导出到电脑的备份；如果当前访问方式无法导出，应先解决备份问题，再进入持久写入步骤。UART 能看到日志并不自动等于拥有 Linux root shell。

### 5.2 用 TFTP 把镜像装入 RAM，再写一个系统槽位

以下沿用作者的示例地址，**电脑 TFTP 服务绑定 `192.168.1.1/24`，路由器 U-Boot 临时地址 `192.168.1.2/24`**。电脑不要同时连接另一台使用 `192.168.1.1` 的设备。将已校验的匹配 UBI 放进 TFTP 根目录，只为所需程序放行本地网络访问。

在 U-Boot 中先加载到 RAM：

```text
setenv ipaddr 192.168.1.2
setenv serverip 192.168.1.1
tftpboot openwrt-ipq50xx-arm-redmi_ax3000-squashfs-nand-factory.ubi
```

这里的文件名仍仅对应已确认的旧版 CR880x；CR881x 需要其目标镜像和独立兼容性核查。TFTP 必须成功，传输字节数与电脑文件长度一致，才考虑写入。协议传输完成不替代下载文件的 SHA256 校验。

**仅当已确认当前原厂系统在 system 1 / `rootfs`，准备写未运行的 system 2 / `rootfs_1`，且分区布局和原厂 `flash` 命令符合作者说明时**，作者的对应命令为：

```text
flash rootfs_1
setenv flag_try_sys2_failed 0
setenv flag_boot_rootfs 1
setenv flag_last_success 1
saveenv
reset
```

逐条检查命令返回；TFTP 或 `flash` 失败时，不设置后续启动变量、不继续 `reset`。如果原厂系统当前运行在 system 2，要写另一槽位时，按[作者的 system 1 示例][S1]核对 `rootfs` 和相应的启动标记，不能固定写 `rootfs_1`。

这个步骤使用已有的原厂 U-Boot，不要求刷入第三方 U-Boot，也不要求写 `MIBIB` 或合并分区。

## 6. 首次启动、后续升级与验收

首次启动后将电脑恢复 DHCP，必要时临时切到 OpenWrt LAN 网段。社区候选常用 `192.168.1.1`；kmiit README 明确给出该地址、用户名 `root`、初始无密码。[kmiit 默认设置][S11] 不同构建以其发布说明为准；Wi-Fi 未广播或没有 LuCI 不直接等于变砖。

先通过有线登录并设置管理员密码，再检查：

| 项目 | 验收内容 |
| --- | --- |
| 设备信息 | `ubus call system board`、`cat /etc/openwrt_release` 与所选目标、版本一致 |
| 闪存与日志 | UBI 正常，无 NAND 探测、挂载失败、持续 panic 或重启 |
| 网口 | WAN/LAN 角色、每个网口、DHCP、DNS；冷启动后重复检查 |
| 无线 | 2.4G/5G 分别连接、近远距离与稳定性；按实际所在地设置国家码 |
| 性能 | 有线 LAN、WAN 路由、PPPoE、无线、加密隧道分别测试，记录 CPU 与温度 |
| 持久性 | 配置保存后重启、断电冷启动，确认没有回滚到原厂 |
| 维护 | 软件源可用，内核模块与固件内核/构建一致，能够追溯源码与校验值 |

160MHz 可能涉及 DFS 等待，先使用较保守的带宽验证基本连接，再按所在地规则启用更宽信道。适配作者 README 提醒了国家码、带宽、信道和雷达检测等待的关系；其中等待时间是其配置示例，不能代替所有地区/信道的规则。[作者无线说明][S1]

不要用主分支没有 NSS 的能力表，推断 QSDK 分支的性能；也不要承诺某构建一定跑满千兆。较新的 ImmortalWrt 也应单独实测，不从旧 QSDK 支持表继承结论。

后续升级时：

- 使用当前系统明确支持、同目标和兼容布局的升级方式。kmiit 有专门的 `redmi,ax3000` 双启动升级代码；这不代表其他目标也支持。[升级实现][S14]
- 有匹配 sysupgrade 镜像时，先核对哈希并运行 `sysupgrade -T` 做平台检查，再按该构建说明升级；检查通过也不替代硬件和布局核验。参数语义可查[官方 sysupgrade 源码][S25]。
- 没有受支持 sysupgrade 路径的历史 UBI 构建，回到其作者流程处理，不使用强制参数绕过不兼容检测。
- 跨 21.02、23.05、24.10 或不同分支时，优先按迁移说明重新配置；不要全量升级旧固件里的全部软件包来代替系统升级。

## 7. 失败与恢复边界

| 现象 | 排查与恢复方向 |
| --- | --- |
| 无法取得 root | 核查实际原厂版本、管理地址、工具日志；需要降级时只使用已确认适配的原厂恢复包 |
| TFTP 没请求或超时 | 检查 LAN 口、Reset 时机、网卡绑定、IP 冲突、防火墙与 TFTP 日志；不以此认定闪存损坏 |
| kernel panic、无法找到 NAND | 串口读日志，核对目标与 NAND 支持；CR881x 的已知型号案例见 Issue #89 |
| 已进入新系统但 LAN 全部失效 | 核对冷启动、交换机初始化；Issue #150 是特定硬件反馈，不是所有 CR8808 的统一诊断 |
| 重启回原厂 | 核查启动变量和失败计数，排除新系统崩溃；不要为了防回滚立即覆盖两个槽位 |
| 新系统不能正常启动，但原厂另一槽位仍完整 | 在可用的 U-Boot 中按记录的原始槽位和启动变量恢复；必须先确认那一槽确实保留原厂系统 |
| 需要重装原厂，原厂引导和布局仍保留 | 使用匹配本机的原厂 TFTP 恢复流程；恢复一般会影响配置 |
| 已换第三方引导或已合并分区 | 原厂 TFTP 可能已不适用；使用该方案明确配套的恢复布局、引导和本机备份 |
| 启动链、分区表或校准区已损坏 | 软件恢复入口可能不可用，需要硬件级恢复评估；重启/Reset 无法补回丢失的本机校准数据 |

这里“保留另一槽”只增加恢复选择；自动回滚、启动环境、闪存坏块等因素仍可能影响恢复。备份应在修改启动链、分区表或系统分区之前完成。

## 8. 本地目录与下一步

```text
cr8808-customize/
├── .gitignore                            # 已添加 /tmp/
├── README.md
├── doc/
│   └── cr8808-openwrt-flashing-research.md # 本文
└── tmp/                                  # 调研中间资料，Git 忽略
    ├── source-index.json                  # 来源、文件 URL、源码 blob SHA
    ├── research-log.md
    ├── hzyitc-*.json / *.txt               # 上游说明、设备定义、发布与问题记录
    ├── xmir-*.json / *.txt                 # 连接、菜单、备份与刷写源码快照
    ├── kmiit-*.json / *.txt                # 较新候选的发布和适配源码
    ├── downloads/                         # 官方版本/设备清单和 URL HEAD 结果
    └── notes/                             # 中间判断
```

后续如下载工具、固件或备份实机，继续使用 `tmp/xmir-patcher/`、`tmp/firmware/`、`tmp/backups/` 和 `tmp/device-info/`；这些目录是使用约定，不表示本次已经生成对应固件或实机备份。

**初次调研要求先记录原厂版本、硬件与分区，再取得 root 并备份。** 本机现已完成上述工作和指定镜像的安装验证，最终命令、返回值与保存位置以[实操记录](cr8808-openwrt-hands-on.md)为准；其他设备仍需独立核对硬件与分区。

初次调研访问部分 OpenWrt Wiki 页面遇到反爬页面，未把这些页面当成已读依据；核心结论采用可读取的官方发布清单、官方公告、项目源码和原始实机记录。初次可达性仅做 HTTP HEAD；后续下载、校验、刷写和重启结果见实操记录。未做吞吐测试或安全审计。

## 9. 一手来源索引

以下来源均于 2026-10-25 核查。GitHub 分支和 snapshot 会继续变化，固定 Release 标签与本地 `tmp/` 快照用于追溯本次结论。

| 编号 | 来源 | 支撑内容 |
| --- | --- | --- |
| S1 | [hzyitc 主分支 README][S1] | 目标、功能限制、原厂 shell 与 UART 安装流程 |
| S2–S4 | [官方稳定版清单][S2]、[官方 snapshot 清单][S3]、[官方 IPQ50xx 定义][S4] | 本次未找到对应官方设备镜像的核查范围 |
| S5 | [Issue #75 原始实机记录][S5] | 主板/SoC 区分、原始型号及原厂入口 |
| S6–S7 | [QSDK 5.4 README][S6]、[OpenWrt 21.02.7 公告][S7] | NSS 支持表与上游停止维护状态 |
| S8–S9 | [社区镜像定义][S8]、[AX3000 DTS][S9] | 目标独立定义与串口配置 |
| S10、S15 | [hzyitc Releases][S10]、[固定 QSDK Release][S15] | 版本、文件名、发布日期和预期校验值 |
| S11–S14 | [kmiit README][S11]、[固定 Release][S12]、[设备定义][S13]、[升级代码][S14] | 较新社区候选的范围与升级实现 |
| S16–S18 | [XMiR-Patcher][S16]、[菜单源码][S17]、[备份源码][S18] | 工具使用、菜单和备份实际行为 |
| S19–S20 | [Issue #89][S19]、[Issue #150][S20] | 特定 NAND、回滚及冷启动交换机问题的用户原始反馈 |
| S21 | [mizu 的 CR8808 实机操作记录][S21] | 串口接线和刷写案例；不是全部步骤均作为本文建议 |
| S22–S24 | [修复工具][S22]、[历史原厂包][S23]、[小米下载页][S24] | 原厂恢复资源入口 |
| S25 | [官方 sysupgrade 源码][S25] | `-T` 的检查模式语义 |
| S26 | [官方版本索引][S26] | 调研时当前稳定版本；不代表特定设备获得支持 |

[S1]: https://github.com/hzyitc/openwrt-redmi-ax3000/blob/ipq50xx-mainline-kernel-5.15-openwrt-23.05/README.md
[S2]: https://downloads.openwrt.org/releases/25.12.6/targets/qualcommax/ipq50xx/profiles.json
[S3]: https://downloads.openwrt.org/snapshots/targets/qualcommax/ipq50xx/profiles.json
[S4]: https://github.com/openwrt/openwrt/blob/main/target/linux/qualcommax/image/ipq50xx.mk
[S5]: https://github.com/hzyitc/openwrt-redmi-ax3000/issues/75
[S6]: https://github.com/hzyitc/openwrt-redmi-ax3000/blob/ipq50xx-qsdk-kernel-5.4-openwrt-21.02-qsdk-11.5.05.841.1029/README.md
[S7]: https://lists.openwrt.org/pipermail/openwrt-announce/2023-May/000041.html
[S8]: https://github.com/hzyitc/openwrt-redmi-ax3000/blob/ipq50xx-mainline-kernel-5.15-openwrt-23.05/target/linux/ipq50xx/image/Makefile
[S9]: https://github.com/hzyitc/openwrt-redmi-ax3000/blob/ipq50xx-mainline-kernel-5.15-openwrt-23.05/target/linux/ipq50xx/dts/ipq5000-ax3000.dts
[S10]: https://github.com/hzyitc/openwrt-redmi-ax3000/releases
[S11]: https://github.com/kmiit/Redmi_AX3000_immortalwrt/blob/redmi_ax3000-24.10/README.md
[S12]: https://github.com/kmiit/Redmi_AX3000_immortalwrt/releases/tag/ci-redmi_ax3000-24.10-20260716-145815-UTC
[S13]: https://github.com/kmiit/Redmi_AX3000_immortalwrt/blob/redmi_ax3000-24.10/target/linux/qualcommax/image/ipq50xx.mk
[S14]: https://github.com/kmiit/Redmi_AX3000_immortalwrt/blob/redmi_ax3000-24.10/target/linux/qualcommax/ipq50xx/base-files/lib/upgrade/platform.sh
[S15]: https://github.com/hzyitc/openwrt-redmi-ax3000/releases/tag/ci-ipq50xx-qsdk-kernel-5.4-openwrt-21.02-qsdk-11.5.05.841.1029-20240727-173350-UTC
[S16]: https://github.com/openwrt-xiaomi/xmir-patcher
[S17]: https://github.com/openwrt-xiaomi/xmir-patcher/blob/main/menu.py
[S18]: https://github.com/openwrt-xiaomi/xmir-patcher/blob/main/create_backup.py
[S19]: https://github.com/hzyitc/openwrt-redmi-ax3000/issues/89
[S20]: https://github.com/hzyitc/openwrt-redmi-ax3000/issues/150
[S21]: https://mizu.reisen/posts/2025-02-23_xiaomi-cr880x-openwrt/
[S22]: https://bigota.miwifi.com/xiaoqiang/tools/MIWIFIRepairTool.x86.zip
[S23]: https://cdn.cnbj1.fds.api.mi-img.com/xiaoqiang/rom/cr8808/miwifi_cr8808_firmware_9d216_6.2.11.bin
[S24]: https://www.miwifi.com/miwifi_download.html
[S25]: https://github.com/openwrt/openwrt/blob/main/package/base-files/files/sbin/sysupgrade
[S26]: https://downloads.openwrt.org/.versions.json
