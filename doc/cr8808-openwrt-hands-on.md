# CR8808 刷入 OpenWrt 实操手册

实操日期：2026-10-25。**已安装并完成重启验证。** 本次使用 ImmortalWrt（OpenWrt 衍生版），保留原厂引导与原厂系统槽。

第一次操作请先读[Windows 新手完整教程](cr8808-beginner-guide.md)，其中包含工具下载和按自己的备份生成脚本的步骤。本文保留本机实际执行的历史记录。

| 项目 | 实测结果 |
| --- | --- |
| 原厂系统 | 管理地址 `192.168.41.1`；后台 `CR8806 / 6.2.33`，底层型号 `CR8808` |
| 硬件线索 | `ap-mp02.1`，`wl_pa_type=xpa`，NAND 页 2048 / 擦除块 131072 字节 |
| 新系统 | `ImmortalWrt 24.10-SNAPSHOT r0-9a11bb8`，内核 `6.6.137` |
| 管理地址 | **http://192.168.1.1**；用户 `root`，密码为本机最后设置的新系统管理员密码 |
| 当前系统槽 | `rootfs_1 / mtd19`；原厂 `rootfs / mtd18` 哈希与备份一致 |
| 有线连接 | 电脑 `192.168.1.135`，LAN1，当前协商速率 100 Mbps |
| 无线 / WAN | 已识别两路无线，暂关闭以避免无密码热点；WAN 未接上游，未测试外网 |

以下记录针对这台实机。设备树里出现 `IPQ5018` 并不单独决定 A/B 版；本次还核对了主板配置、NAND、原厂分区及无线 board ID。其他硬件不能直接套用写入步骤。

## 1. 查看原厂型号和固件版本

**电脑 PowerShell 7：**

```powershell
Set-Location 'D:\yingj\workspace\cr8808-customize'
$info = Invoke-RestMethod -NoProxy -Uri 'http://192.168.41.1/cgi-bin/luci/api/xqsystem/init_info'
$info | Select-Object code, hardware, romversion
```

实际返回：

```text
code hardware romversion
---- -------- ----------
   0 CR8806   6.2.33
```

本机代理曾导致 `502 Bad Gateway`，绕过代理后正常。PowerShell 5.1 可用 `curl.exe --noproxy "*" http://192.168.41.1/cgi-bin/luci/api/xqsystem/init_info`。

## 2. 使用 XMiR-Patcher 获取 root

**电脑 PowerShell，工具已下载则跳过 clone：**

```powershell
git clone https://github.com/openwrt-xiaomi/xmir-patcher.git .\tmp\xmir-patcher
$env:NO_PROXY = '192.168.41.1,127.0.0.1,localhost'
Push-Location .\tmp\xmir-patcher
.\run.bat
Pop-Location
```

主菜单选 `1`，填写 `192.168.41.1`；再选 `2`，输入原厂后台管理密码。成功后选 `3` 读取设备信息。

本次工具提交：`16a46e350e3de2cb3415ab2cb652df53783998dc`。第一组方法失败后，`connect5 / smartcontroller` 成功，耗时数分钟：

```text
Exploits "arn_switch/start_binding/set_mac_filter/datacenter7" not working!!!
Enable smartcontroller scene executor ...
Unlock SSH server ...
#### SSH server are activated! ####
```

## 3. 登录 root，确认分区并修改 SSH 密码

**电脑：** `ssh root@192.168.41.1`。如旧原厂只提供 `ssh-rsa`，按提示增加 `-o HostKeyAlgorithms=+ssh-rsa`。

工具初始临时密码为 `root`，取得权限后执行 `passwd` 设置自己的密码。本次通过本机掩码输入框设置并重新登录验证，密码没有写入文档或日志。

**路由器 shell，实际返回节选：**

```text
# id
uid=0(root) gid=0(root)
# nvram get model
CR8808
# cat /tmp/sysinfo/board_name
ap-mp02.1
# cat /proc/cmdline
ubi.mtd=rootfs root=mtd:ubi_rootfs rootfstype=squashfs rootwait swiotlb=1
# cat /proc/mtd（关键行）
mtd18: 02400000 00020000 "rootfs"
mtd19: 02400000 00020000 "rootfs_1"
```

因此本次当前系统是 `mtd18`，待写入的另一系统槽是 `mtd19`。

## 4. 备份原厂分区

回到 XMiR 主菜单，选 `4 - Create full backup`。文件保存在 `tmp/xmir-patcher/backups/`。

本次对每个下载分块额外执行路由器端 `openssl dgst -sha256 /tmp/mtd_dump.bin`，与电脑收到的内容比对，再检查最终文件长度。原厂没有 `sha256sum` 命令。

实际结果：**22 个物理 NAND 分区，共 127 MiB；另外保存 2 个可读 UBI 逻辑视图。** `mtd24` 逻辑视图读取未通过检查，`mtd25` 未单独导出；对应的物理分区已经完整备份，不把零长度逻辑文件计入成功清单。

在电脑重新核验：

```powershell
$backupDir = '.\tmp\xmir-patcher\backups'
$manifest = Get-Content "$backupDir\backup-manifest.json" -Raw | ConvertFrom-Json
foreach ($part in $manifest.partitions) {
    $file = Join-Path $backupDir $part.file
    if ((Get-Item $file).Length -ne $part.bytes) { throw "长度不匹配：$file" }
    if ((Get-FileHash $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $part.sha256) { throw "哈希不匹配：$file" }
}
'24 个完整备份文件校验通过'
```

第二份本地副本：`C:\Users\yingj\cr8808-backups\2026-10-25-192.168.41.1\cr8808-stock-after-ssh-backup.zip`。压缩包内容的 SHA256 已复核。这是运行中、开启 SSH 后的分区备份，不包含 NAND OOB 或未分区空间。

## 5. 确认有线通路，下载并校验固件

**电脑：**

```powershell
Get-NetAdapter | Select-Object Name, Status, LinkSpeed
Get-NetIPAddress -InterfaceAlias '以太网' -AddressFamily IPv4 | Select-Object IPAddress
ssh -b 192.168.41.90 root@192.168.41.1
```

刷写前实测：有线地址 `192.168.41.90`；路由器交换机 LAN1 已识别电脑有线网卡，`link:up speed:100baseT full-duplex`。网口灯不亮时，以链路状态和有线 SSH 验证为准，网页经 Wi-Fi 可达不能代替这一步。

本次曾短暂添加路由器维护地址 `192.168.32.251/32` 做排查，未建立通路，已在刷写前移除。Windows 管理员配置窗口被取消，没有执行电脑临时地址配置。

**电脑 PowerShell：**

```powershell
New-Item -ItemType Directory -Force .\tmp\firmware | Out-Null
$image = '.\tmp\firmware\immortalwrt-redmi_ax3000-factory.ubi'
$url = 'https://github.com/kmiit/Redmi_AX3000_immortalwrt/releases/download/ci-redmi_ax3000-24.10-20260716-145815-UTC/immortalwrt-qualcommax-ipq50xx-redmi_ax3000-squashfs-factory.ubi'
Invoke-WebRequest -Uri $url -OutFile $image
$expected = '897fd05dd6584e820aeb99905191dd8532564758c12db486e8041625d00797e7'
if ((Get-FileHash $image -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'SHA256 不匹配，停止' }
scp -O $image root@192.168.41.1:/tmp/cr880x-factory.ubi
```

**路由器：**

```sh
openssl dgst -sha256 /tmp/cr880x-factory.ubi
```

电脑与路由器都返回上述 SHA256，文件长 `17694720` 字节；UBI 擦除块 128 KiB、VID 偏移 2048、数据偏移 4096，FIT 包含 `config@mp02.1`。

## 6. 写入另一系统槽，校验后切换启动标记

本次使用文末完整脚本，先核对主板、原厂布局、当前槽位及固件/引导/校准哈希，再写入 `mtd19`，读回数据页校验通过后才修改启动标记。将文末脚本保存为电脑上的 `tmp/notes/flash-inactive-slot.sh`，再上传：

```powershell
scp -O .\tmp\notes\flash-inactive-slot.sh root@192.168.41.1:/tmp/flash-inactive-slot.sh
```

**路由器 root shell：**

```sh
sh /tmp/flash-inactive-slot.sh
```

实际关键返回：

```text
PREFLIGHT_COMPLETE: active=rootfs/mtd18, target=rootfs_1/mtd19
ubiformat: mtd19 (nand), size 37748736 bytes (36.0 MiB), 288 eraseblocks
READBACK_PAGES_SHA256_OK: 1800e2bbdfb0aa76e81497c555c2c8122c980af75b33eddf158e0ceac4d4bf08
FLASH_AND_BOOT_FLAGS_COMPLETE
```

`ubiformat` 会更新擦除计数等 EC 头部，因此读回校验比较的是每块首个 2048 字节页之后的全部页面，包含 VID 头和卷数据；它不是与下载文件做整文件哈希相等比较。完整日志在 `tmp/device-info/flash-full-output.txt`。

## 7. 重启，登录新系统并设置管理员密码

**原厂 root shell：**

```sh
reboot
```

等待有线连接恢复，必要时在电脑执行 `ipconfig /renew "以太网"`。本次电脑自动获得 `192.168.1.135`。

打开 **http://192.168.1.1**；SSH 使用 `ssh root@192.168.1.1`。首次启动初始免密，随后执行 `passwd` 设置新系统管理员密码。本次已设置，并分别验证 SSH 密码认证和 LuCI 登录（HTTP 200）。**最终使用本机最后一次设置的新系统密码。**

新系统 SSH 使用 Windows 自带客户端；旧 XMiR 内置客户端曾报密钥协商错误，这不代表设备启动失败。LuCI 未登录时返回过带登录表单的 HTTP 403，完成登录后正常。

## 8. 验证启动槽、驱动和重启后配置

**新系统 root shell：**

```sh
ubus call system board
cat /proc/cmdline
df -h
iw phy | grep '^Wiphy'
```

本次实际结果节选：

```text
model:        Redmi AX3000
board_name:   redmi,ax3000
distribution: ImmortalWrt
version:      24.10-SNAPSHOT
revision:     r0-9a11bb8
kernel:       6.6.137

ubi.mtd=rootfs_1 ... root=/dev/ubiblock0_1 coherent_pool=2M
/dev/ubi0_2  12.8M  ... /overlay
Wiphy phy1
Wiphy phy0
```

已再重启一次：新系统密码、LuCI 登录和 `rootfs_1` 启动槽均保持正常。UBI 日志为 `bad PEBs: 0, corrupted PEBs: 0`；分区表 `mtd1`、引导 `mtd11`、校准 `mtd13` 和原厂系统 `mtd18` 的 SHA256 均与备份一致。

该构建默认开启名为 `ImmortalWrt` 的无密码热点，本次已关闭两路无线并验证重启后仍关闭。可在 LuCI 的“网络 → 无线”中设置 WPA2/WPA3 密码后启用。WAN 当前未接上游，未验证外网、吞吐或断电冷启动。

最终验证数据：`tmp/device-info/postflash-verification.json`；操作状态：`tmp/device-info/operation-status.json`。中间材料和设备备份继续保存在 Git 忽略的 `tmp/`。

<details>
<summary>历史实机脚本（含本机备份哈希，不能直接用于其他设备）</summary>

```sh
#!/bin/sh
# This device only: CR8808, ap-mp02.1, original mtd18/mtd19 layout.
# No reboot: write, verify programmed pages, then commit boot flags.
set -eu

IMAGE=/tmp/cr880x-factory.ubi
IMAGE_SHA256=897fd05dd6584e820aeb99905191dd8532564758c12db486e8041625d00797e7
PROGRAMMED_PAGES_SHA256=1800e2bbdfb0aa76e81497c555c2c8122c980af75b33eddf158e0ceac4d4bf08

for tool in openssl ubiformat nvram awk dd strings; do
    command -v "$tool" >/dev/null
done
[ "$(id -u)" = 0 ]
[ "$(nvram get model)" = CR8808 ]
[ "$(cat /tmp/sysinfo/board_name)" = ap-mp02.1 ]
tr '\000' '\n' < /proc/device-tree/compatible | grep -qx 'qcom,ipq5018-mp02.1'
[ "$(strings /dev/mtdblock15 | sed -n 's/^wl_pa_type=//p' | head -n 1)" = xpa ]
[ "$(awk '$4 == "\"rootfs\"" {print $1, $2}' /proc/mtd)" = 'mtd18: 02400000' ]
[ "$(awk '$4 == "\"rootfs_1\"" {print $1, $2}' /proc/mtd)" = 'mtd19: 02400000' ]
[ "$(sed -n 's/.*ubi\.mtd=\([^ ]*\).*/\1/p' /proc/cmdline)" = rootfs ]
[ "$(nvram get flag_boot_rootfs)" = 0 ]
[ "$(nvram get flag_last_success)" = 0 ]
[ "$(cat /sys/class/mtd/mtd19/type)" = nand ]
[ "$(cat /sys/class/mtd/mtd19/writesize)" = 2048 ]
[ "$(cat /sys/class/mtd/mtd19/erasesize)" = 131072 ]
for entry in /sys/class/ubi/ubi[0-9]*/mtd_num; do
    [ -f "$entry" ] || continue
    [ "$(cat "$entry")" != 19 ]
done
[ "$(wc -c < "$IMAGE" | tr -d ' ')" = 17694720 ]
[ "$(openssl dgst -sha256 "$IMAGE" | awk '{print $NF}')" = "$IMAGE_SHA256" ]
# Confirm the backed-up partition table, original bootloader and calibration.
[ "$(openssl dgst -sha256 /dev/mtd1 | awk '{print $NF}')" = c56efb1b07051d2c799b20cec147ac5ba672a72c5bad4529ec7de865ac54becd ]
[ "$(openssl dgst -sha256 /dev/mtd11 | awk '{print $NF}')" = efc7029a2bcf445fa6a07ac5817691417a2b147c54403d0ac7c0ae9f3feb1051 ]
[ "$(openssl dgst -sha256 /dev/mtd13 | awk '{print $NF}')" = cc1d8cc28a104608dd23f4735faf61bd1e19a8ff203250719d037af2a2a83b15 ]
echo 'PREFLIGHT_COMPLETE: active=rootfs/mtd18, target=rootfs_1/mtd19'

ubiformat /dev/mtd19 -y -f "$IMAGE"

# ubiformat regenerates erase-counter headers in the first 2048-byte page.
# Compare all following pages, including VID headers and volume data, with
# the selected 135-PEB image. A bad-block shift or short read stops boot switching.
READBACK_SHA256=$(
    (
        block=0
        while [ "$block" -lt 135 ]; do
            dd if=/dev/mtd19 bs=2048 skip=$((block * 64 + 1)) count=63 2>/dev/null || exit 1
            block=$((block + 1))
        done
    ) | openssl dgst -sha256 | awk '{print $NF}'
)
[ "$READBACK_SHA256" = "$PROGRAMMED_PAGES_SHA256" ]
echo "READBACK_PAGES_SHA256_OK: $READBACK_SHA256"

nvram set flag_try_sys2_failed=0
nvram set flag_boot_rootfs=1
nvram set flag_last_success=1
nvram commit
sync
[ "$(nvram get flag_try_sys2_failed)" = 0 ]
[ "$(nvram get flag_boot_rootfs)" = 1 ]
[ "$(nvram get flag_last_success)" = 1 ]
echo 'FLASH_AND_BOOT_FLAGS_COMPLETE'
```

</details>

固件来源：[固定 Release](https://github.com/kmiit/Redmi_AX3000_immortalwrt/releases/tag/ci-redmi_ax3000-24.10-20260716-145815-UTC)、[固定设备定义](https://github.com/kmiit/Redmi_AX3000_immortalwrt/blob/ci-redmi_ax3000-24.10-20260716-145815-UTC/target/linux/qualcommax/image/ipq50xx.mk)。该仓库已归档，此 Release 标为预发布，本次完成的是指定镜像的实机安装与基础验证；不代表仍有持续更新。其他硬件路线与恢复说明见[完整调研](cr8808-openwrt-flashing-research.md)。
