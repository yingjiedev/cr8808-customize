# CR8808 刷入 OpenWrt：Windows 新手教程

根据 2026-10-25 的成功实操整理：**原厂系统 → 获取 root → 备份 → 写入另一系统槽 → ImmortalWrt → 重启验收**。

**本项目这台路由器已经刷完。本文用于学习和同条件复现，不需要在已刷好的系统上重新执行原厂刷写步骤。**

本次安装的是 OpenWrt 衍生版 **ImmortalWrt 24.10-SNAPSHOT r0-9a11bb8**，内核 `6.6.137`。使用固定版本复现；固件来源仓库已归档，Release 标为预发布，不代表仍有持续维护。来源和原始日志摘要见[实操记录](cr8808-openwrt-hands-on.md)。

## 0. 先确定能否使用这篇教程

这篇教程只覆盖本次验证过的一条路线：

| 条件 | 本次实机 |
| --- | --- |
| 原厂后台 | 显示 `CR8806 / 6.2.33` |
| 底层型号 | `nvram get model` 返回 `CR8808` |
| 主板配置 | `ap-mp02.1`，`wl_pa_type=xpa` |
| 原厂系统分区 | `mtd18=rootfs`、`mtd19=rootfs_1`，每个 36 MiB |
| 当前启动槽 | `ubi.mtd=rootfs`，启动标记为 `0` |
| NAND | 页 2048 字节、擦除块 131072 字节、OOB 64 字节 |
| 刷写方式 | 保留原厂引导和分区表，只写未运行的 `mtd19` |

**只有“外壳写 CR8808”或“M79”不够。** 如果是 CR881x、其他主板配置、已经换过第三方引导/合并分区，或当前运行在 `rootfs_1`，不要继续本文的写入步骤，先看[硬件分流调研](cr8808-openwrt-flashing-research.md)。脚本检查也不能代替硬件与历史核对。

下面所有返回值都以本次实机为例。地址、网卡名称和自己的备份哈希会不同；固件文件名、长度和固件 SHA256 必须与本文固定版本一致。

## 1. 准备电脑、下载项目和工具

准备 Windows 10/11 x64 电脑、网线、稳定的路由器电源，以及至少 1 GB 可用磁盘空间。你需要知道原厂**后台管理密码**。

### 1.1 认识两个窗口

| 看到的提示符 | 在哪里 | 应执行什么 |
| --- | --- | --- |
| `PS C:\cr8808>` | 电脑 PowerShell | 下载、校验文件、`ssh.exe`、`scp.exe` |
| `root@XiaoQiang:~#` 等 | 已登录原厂路由器的 SSH | `id`、`nvram`、`cat /proc/mtd`、原厂刷写脚本 |
| `root@ImmortalWrt:~#` | 新系统的 SSH | `passwd`、`ubus`、`uci` |

代码块上方会标明执行位置。**不要把提示符、返回值一起复制执行。** SSH 中执行 `exit` 只是退出登录，回到电脑；执行 `reboot` 才是重启路由器。

### 1.2 下载本项目

打开[项目仓库](https://github.com/yingjiedev/cr8808-customize)，点击 **Code → Download ZIP**，解压后将包含 `README.md`、`doc`、`scripts` 的文件夹放到 `C:\cr8808`。

仓库目前是私有仓库，需要先用有访问权限的 GitHub 账号登录。不要把外层解压目录误当成项目根目录。

打开 PowerShell。后面标注“电脑”的命令尽量一直在这个窗口执行，保留变量：

```powershell
$ErrorActionPreference = 'Stop'
$Project = 'C:\cr8808'
$RouterIP = '192.168.41.1'
Set-Location $Project
Get-ChildItem
New-Item -ItemType Directory -Force .\tmp | Out-Null
```

**如何判断：** 能看到 `doc`、`scripts` 和 `README.md`。如果你放在其他目录，只修改 `$Project`。本次原厂地址是 `192.168.41.1`；你的后台若是其他地址，修改 `$RouterIP`，不要直接改成新系统的 `192.168.1.1`。

### 1.3 检查 Windows 的 SSH/SCP 客户端

**电脑 PowerShell：**

```powershell
Get-Command ssh.exe, scp.exe, curl.exe | Select-Object Name, Source
```

正常会列出三个程序，SSH/SCP 通常位于 `C:\Windows\System32\OpenSSH\`。

如果缺少 SSH/SCP，在 Windows“设置 → 可选功能”中安装 **OpenSSH 客户端**；这里不需要安装 OpenSSH 服务器。也可在**管理员 PowerShell**执行下面这一条，安装完成后回到普通 PowerShell 继续。[微软安装说明](https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse)

```powershell
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

典型安装结果：`Online : True`、`RestartNeeded : False`。安装功能需要管理员权限；后面的本地校验和正常 SSH 操作不要求一直使用管理员窗口。

### 1.4 下载本次使用的 XMiR-Patcher

工具来源：[上游项目](https://github.com/openwrt-xiaomi/xmir-patcher)、[本次固定版本 ZIP](https://github.com/openwrt-xiaomi/xmir-patcher/archive/16a46e350e3de2cb3415ab2cb652df53783998dc.zip)。这个 Windows 压缩包包含 Python 运行时，不需要另外安装 Python 或 Git。

**电脑 PowerShell：**

```powershell
$XmirCommit = '16a46e350e3de2cb3415ab2cb652df53783998dc'
$ToolDir = Join-Path $Project "tmp\xmir-patcher-$XmirCommit"
if (-not (Test-Path -LiteralPath $ToolDir)) {
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/openwrt-xiaomi/xmir-patcher/archive/$XmirCommit.zip" -OutFile .\tmp\xmir-patcher.zip
    Expand-Archive -LiteralPath .\tmp\xmir-patcher.zip -DestinationPath .\tmp
}
Test-Path (Join-Path $ToolDir 'run.bat')
Test-Path (Join-Path $ToolDir 'python\python.exe')
```

**如何判断：** 最后两行都是 `True`。如果不是，先检查解压目录；不要直接运行压缩包内的 `run.bat`。

## 2. 接好 LAN 网线，确认原厂管理地址

电脑网口连接路由器 **LAN 口**。可以暂时保留电脑另一块网卡上网，但后面 SSH 必须绑定连这台路由器的有线地址。

**电脑 PowerShell：**

```powershell
Get-NetAdapter | Select-Object Name, Status, LinkSpeed
```

先找到实际连接路由器的网卡。下面以名称 `以太网` 为例；若用 USB 网卡，可能是 `以太网 3`，请修改：

```powershell
$WiredName = '以太网'
Get-NetIPAddress -InterfaceAlias $WiredName -AddressFamily IPv4 | Select-Object IPAddress, PrefixLength
```

本次连通后的例子：

```text
Name    Status LinkSpeed
----    ------ ---------
以太网  Up     100 Mbps

IPAddress       PrefixLength
---------       ------------
192.168.41.90              24
```

**继续条件：** 网卡为 `Up`，电脑和原厂路由器处于正确网段。本次 `/24` 网络中，电脑是 `192.168.41.x`，路由器是 `192.168.41.1`。

如果是 `Disconnected`，先重插两端、换 LAN 口或换线；如果是 `169.254.x.x` 或仍是旧网络地址，先检查接线与网卡，再尝试 `ipconfig /renew "$WiredName"`。网口灯不亮不能单独判断失败，本次最后以链路状态和有线 SSH 证实连通。

打开浏览器登录 `http://192.168.41.1`（换成你的原厂地址），再在电脑读取版本：

```powershell
$raw = curl.exe --noproxy "*" --connect-timeout 5 --max-time 10 --fail --silent --show-error "http://$RouterIP/cgi-bin/luci/api/xqsystem/init_info"
if ($LASTEXITCODE -ne 0) { throw '无法直连原厂接口，先解决地址或接线问题' }
$info = $raw | ConvertFrom-Json
$info | Select-Object code, hardware, romversion
```

本次返回：

```text
code hardware romversion
---- -------- ----------
   0 CR8806   6.2.33
```

**如何判断：** `code=0`，能看到型号和版本。后台显示 `CR8806` 而外壳是 CR8808，不要马上选包，下一步还要读底层信息。本次普通代理请求曾返回 502，使用 `curl.exe --noproxy` 直连后正常。

## 3. 获取 root，并设置原厂 SSH 密码

**电脑 PowerShell：**

```powershell
$env:NO_PROXY = "$RouterIP,192.168.1.1,127.0.0.1,localhost"
Push-Location $ToolDir
.\run.bat
Pop-Location
```

工具主菜单中按顺序输入，输入一次按一次 Enter：

1. `1`：填写原厂路由器地址，本次是 `192.168.41.1`。
2. `2`：按提示输入原厂**后台管理密码**，等待获取访问权限。
3. `3`：读取完整设备信息。
4. `0`：退出工具，回到电脑 PowerShell。

本次第一组方法失败，随后自动尝试 `smartcontroller` 成功。看到第一条失败不要立刻关闭，查看后续结果：

```text
Exploits "arn_switch/start_binding/set_mac_filter/datacenter7" not working!!!
Enable smartcontroller scene executor ...
Unlock dropbear service ...
Unlock SSH server ...
#### SSH server are activated! ####
```

**获取权限失败且没有成功标记：** 保存原厂版本和最后错误，停在这里。不要随便降级或换其他型号的原厂包。

**电脑 PowerShell，先记下正确的有线地址：**

```powershell
$WiredIP = '192.168.41.90'
ssh.exe -b $WiredIP -o HostKeyAlgorithms=+ssh-rsa "root@$RouterIP"
```

将 `$WiredIP` 改为第 2 步查到的地址。`-b` 让这次 SSH 使用该有线地址，避免实际上仍通过 Wi-Fi 连接。

首次连接通常询问 `Are you sure you want to continue connecting ...?`。核对是你直连的这台路由器后输入 `yes`。密码输入时没有字符或星号显示，这是正常现象。

工具在本次流程中把初始 SSH 密码设为 `root`；如果工具提示了其他值，或你已经改过密码，以实际值为准。登录后在**路由器 SSH**执行：

```sh
id
passwd
```

典型返回：

```text
uid=0(root) gid=0(root)
Changing password for root
New password:
Retype password:
passwd: password for root changed by root
```

**如何判断：** `uid=0(root)` 才是 root。`passwd` 要输入两次自己的新 SSH 密码；原厂后台密码与这个密码分开记录。在路由器执行 `exit` 回到原来的电脑 PowerShell，再执行上面的 `ssh.exe -b ...` 命令，用新密码重新登录。验证成功后，保持在路由器 SSH 中继续第 4 步。

## 4. 确认硬件、分区与当前启动槽

**原厂路由器 SSH：**

```sh
nvram get model
cat /tmp/sysinfo/board_name
tr '\000' '\n' < /proc/device-tree/compatible
strings /dev/mtdblock15 | sed -n 's/^wl_pa_type=//p' | head -n 1
cat /proc/mtd
cat /proc/cmdline
nvram get flag_boot_rootfs
nvram get flag_last_success
cat /sys/class/mtd/mtd19/writesize
cat /sys/class/mtd/mtd19/erasesize
cat /sys/class/mtd/mtd19/oobsize
```

和下面逐项对照：

| 检查 | 本次返回 / 本教程要求 |
| --- | --- |
| `nvram get model` | `CR8808` |
| 主板 | `ap-mp02.1` |
| compatible | 包含 `qcom,ipq5018-mp02.1` |
| `wl_pa_type` | `xpa` |
| 分区 | `mtd18: 02400000 00020000 "rootfs"` |
| 分区 | `mtd19: 02400000 00020000 "rootfs_1"` |
| cmdline | 包含 **`ubi.mtd=rootfs`** |
| 两个启动标记 | 都为 `0` |
| NAND 参数 | 依次为 `2048`、`131072`、`64` |

**任一项不符就停止本文路线。** 本次 `IPQ5018` 是设备树中的公共平台标识，不能仅凭这个字符串改刷 `xiaomi_cr881x`。本教程写入方向固定为当前 `rootfs/mtd18` → 另一槽 `rootfs_1/mtd19`，不自动适配相反方向。

## 5. 备份并生成“这台设备专用”的刷写脚本

先在 SSH 执行 `exit` 回电脑。重新启动 XMiR：

```powershell
Push-Location $ToolDir
.\run.bat
Pop-Location
```

主菜单选择 **`4 - Create full backup`**。如果询问 root 密码，输入第 3 步刚改的新 SSH 密码。完成后选 `0` 退出。

备份在 `$ToolDir\backups`；分区资料在 `$ToolDir\outdir`。典型日志：

```text
Full backup creating...
Backup of "0ART" saved to file "./backups/mtd13_0ART.bin"
Backup of "rootfs" saved to file "./backups/mtd18_rootfs.bin"
Backup of "rootfs1" saved to file "./backups/mtd19_rootfs1.bin"
```

工具的 `Completed!` 不足以证明所有文件完整。接着在**电脑 PowerShell**执行本项目的校验工具：

```powershell
Set-Location $Project
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\prepare-cr8808-flash.ps1 -ToolDirectory $ToolDir
if ($LASTEXITCODE -ne 0) { throw '备份检查失败，停止，不要刷写' }
```

这里的 `ExecutionPolicy Bypass` 仅用于这次子进程执行，不修改全局策略。脚本只检查本地备份并生成文件，不连接路由器。

正常返回大致如下：

```text
BACKUP_OK: 22 physical partitions, 133169152 bytes (127 MiB).
MANIFEST: C:\cr8808\tmp\prepared\backup-manifest.json
FLASH_SCRIPT: C:\cr8808\tmp\prepared\flash-current-device.sh
Local SHA256 records created. Router preflight must still pass.
No router was contacted or flashed.
```

**如何判断：** 必须看到 `BACKUP_OK`，且进程退出码为 0。它核对 22 个物理分区的名称、布局和文件长度，为文件计算本地 SHA256，并把你自己的分区表/引导/校准/原厂系统备份哈希写入专用脚本。路由器上还会把这些哈希与当前分区比较。

本次还读取了两个 UBI 逻辑视图；`mtd24` 读取未通过检查，`mtd25` 没有单独导出。**逻辑视图不能当成额外物理分区。** 在本文明确匹配的布局中，校验器确认的 `mtd0–mtd21` 已覆盖全部暴露的物理分区；任何一个物理分区缺失或长度不符都会拒绝生成脚本。

标准 XMiR 菜单没有本教程额外的逐块 SHA256 比对。这里生成的是本地文件校验记录，加上刷写前的关键分区远端哈希核对；本次实操的额外逐块校验见实操记录，不能把两者混为一谈。

**继续前，把 `backups`、`outdir` 和 `tmp/prepared` 复制到第二个存储位置。** 这是开启 SSH 后的运行中分区备份，不含 NAND OOB、未分区空间，也不是全分区同一时刻的快照。不要使用别人机器的备份。

从备份到刷写之间不要另做升级或重启原厂系统；如果状态已经改变，重新备份和生成脚本，避免拿旧哈希强行通过检查。

生成的 `flash-current-device.sh` 也留在本地。不要把实操记录里写死的本机哈希、其他人的校准哈希复制到你的脚本中。

## 6. 下载固定系统镜像，校验后上传

来源：[固定 Release 页面](https://github.com/kmiit/Redmi_AX3000_immortalwrt/releases/tag/ci-redmi_ax3000-24.10-20260716-145815-UTC)。页面标有 `Pre-release`，仓库已归档；本教程复现这个已经实机启动过的固定版本。

| 文件 | 本教程用途 |
| --- | --- |
| **`...redmi_ax3000-squashfs-factory.ubi`** | 本次从原厂系统首次刷入，下载这一份 |
| `...sysupgrade.bin` | 匹配的新系统内部升级，不用于本次首次安装 |
| `...initramfs-uImage.itb` | RAM 启动/调试，不按本文写入 |

**电脑 PowerShell：**

```powershell
Set-Location $Project
New-Item -ItemType Directory -Force .\tmp\firmware | Out-Null
$Image = '.\tmp\firmware\immortalwrt-redmi_ax3000-factory.ubi'
$FirmwareURL = 'https://github.com/kmiit/Redmi_AX3000_immortalwrt/releases/download/ci-redmi_ax3000-24.10-20260716-145815-UTC/immortalwrt-qualcommax-ipq50xx-redmi_ax3000-squashfs-factory.ubi'
Invoke-WebRequest -UseBasicParsing -Uri $FirmwareURL -OutFile $Image
$Expected = '897fd05dd6584e820aeb99905191dd8532564758c12db486e8041625d00797e7'
$Actual = (Get-FileHash -LiteralPath $Image -Algorithm SHA256).Hash.ToLowerInvariant()
Get-Item -LiteralPath $Image | Select-Object Name, Length
$Actual
if ($Actual -ne $Expected) { throw '固件 SHA256 不匹配，停止' }
```

应看到长度 **`17694720`** 字节，SHA256 完整等于：

```text
897fd05dd6584e820aeb99905191dd8532564758c12db486e8041625d00797e7
```

下载完成不等于校验通过。SHA256 能确认文件与发布值一致，不能代替对来源和硬件的核对。

**电脑 PowerShell，上传镜像和刚生成的专用脚本：**

```powershell
scp.exe -O -o "BindAddress=$WiredIP" -o HostKeyAlgorithms=+ssh-rsa $Image "root@${RouterIP}:/tmp/cr880x-factory.ubi"
if ($LASTEXITCODE -ne 0) { throw '固件上传失败，停止' }
scp.exe -O -o "BindAddress=$WiredIP" -o HostKeyAlgorithms=+ssh-rsa .\tmp\prepared\flash-current-device.sh "root@${RouterIP}:/tmp/flash-current-device.sh"
if ($LASTEXITCODE -ne 0) { throw '脚本上传失败，停止' }
```

SCP 通常显示文件名和 `100%`；应没有连接或权限错误。`-O` 使用旧 SCP 协议，适用于原厂没有 SFTP 的情况；SCP 绑定有线地址使用 `-o BindAddress=...`，不是 SSH 的 `-b`。

电脑项目的 `tmp` 和路由器的 `/tmp` 是两个目录。继续用之前的方式登录原厂 SSH，在**路由器**执行：

```sh
openssl dgst -sha256 /tmp/cr880x-factory.ubi
wc -c /tmp/cr880x-factory.ubi
```

典型返回：

```text
SHA256(/tmp/cr880x-factory.ubi)= 897fd05dd6584e820aeb99905191dd8532564758c12db486e8041625d00797e7
17694720 /tmp/cr880x-factory.ubi
```

**继续条件：** 路由器端的哈希和长度也一致。不要因为原厂没有 `sha256sum` 就跳过，使用已有的 `openssl`。

## 7. 先只检查，再执行刷写

**原厂路由器 root SSH，先执行检查模式：**

```sh
sh /tmp/flash-current-device.sh --check
```

正常返回：

```text
PREFLIGHT_OK: active=rootfs/mtd18 target=rootfs_1/mtd19
CHECK_ONLY_COMPLETE: no flash or boot-flag writes
```

**如何判断：** 必须出现这两行，且没有 `STOP`。检查模式不写系统槽和启动标记。不带参数运行也默认只检查。模板文件本身不能直接运行，必须先用自己的完整备份生成脚本。

检查通过，确认电源和有线连接稳定，再执行下面一条。**这是实际擦除并写入 `mtd19` 的步骤。**

```sh
sh /tmp/flash-current-device.sh --flash
```

过程会显示扫描、刷写、格式化进度，最后应看到：

```text
PREFLIGHT_OK: active=rootfs/mtd18 target=rootfs_1/mtd19
ubiformat: mtd19 (nand), size 37748736 bytes (36.0 MiB), 288 eraseblocks ...
READBACK_PAGES_SHA256_OK: 1800e2bbdfb0aa76e81497c555c2c8122c980af75b33eddf158e0ceac4d4bf08
FLASH_AND_BOOT_FLAGS_COMPLETE: inspect output, then run reboot separately
```

**如何判断：** 必须看到读回校验通过和最后的 `FLASH_AND_BOOT_FLAGS_COMPLETE`。脚本依次校验、写入、读回比较、提交启动标记，不自动重启。`ubiformat` 会更新 EC 擦除计数头，所以读回比较的是排除每块首个 2048 字节页后的页面，包含 VID 头与卷数据。

出现 `STOP`、读取/写入错误、哈希不符，或缺少完成标记：保留全部输出，停在这里。不要删掉检查、覆盖两个槽位或继续重启。读回方法针对这个固定镜像和已验证的无坏块情况；出现坏块偏移也会停止切换。

## 8. 重启并登录新系统

**只有上一步完整成功后，在原厂 SSH 执行：**

```sh
reboot
```

SSH 断开正常。等待约 1–3 分钟，有线链路会短暂断开再恢复。电脑网卡保持自动获取地址；必要时在电脑执行：

```powershell
ipconfig /renew "$WiredName"
Get-NetIPAddress -InterfaceAlias $WiredName -AddressFamily IPv4 | Select-Object IPAddress
```

本次新地址为 **`192.168.1.135`**。你只需确认变成 `192.168.1.x`，不要求和这个尾号相同。

浏览器打开 **http://192.168.1.1**，用户名 `root`。该构建初始免密。电脑 SSH 也绑定新取得的有线地址，下面的尾号 `135` 改成你实际查到的值：

```powershell
$NewWiredIP = '192.168.1.135'
ssh.exe -b $NewWiredIP root@192.168.1.1
```

**新系统 SSH：** 该构建默认开启无密码热点，先关闭两路无线，再设置新系统管理员密码：

```sh
uci set wireless.radio0.disabled=1
uci set wireless.radio1.disabled=1
uci commit wireless
wifi reload
passwd
```

`passwd` 再次输入两遍自己的密码。这是新系统的密码，不会自动沿用原厂后台或原厂 SSH 密码；设置后，Web 和 SSH 都用这个新系统 root 密码。

退出并重新登录 SSH，浏览器也用新密码登录。**继续条件：** 两种登录都成功。本次认证后的 LuCI HTTP 状态为 200；未登录时曾返回带登录表单的 403，不等于路由器变砖。

## 9. 验收，再重启一次确认持久性

**新系统 SSH：**

```sh
ubus call system board
cat /proc/cmdline
df -h
iw phy | grep '^Wiphy'
dmesg | grep -E 'attached mtd19|bad PEBs|corrupted PEBs'
```

和下表对照：

| 检查 | 本次返回 | 如何判断 |
| --- | --- | --- |
| 设备定义 | `model: Redmi AX3000`、`board_name: redmi,ax3000` | 这是社区适配目标的名称，不是硬件被改成另一型号 |
| 系统 | `ImmortalWrt 24.10-SNAPSHOT r0-9a11bb8` | 与固定 Release 对应 |
| 内核 | `6.6.137` | 与本次构建一致 |
| 启动槽 | cmdline 含 `ubi.mtd=rootfs_1` | 已从新写入槽启动 |
| 可写空间 | `/overlay` 约 12.8 MiB | 可写 overlay 正常挂载；`/rom` 显示 100% 是只读系统镜像的正常现象 |
| 无线设备 | `Wiphy phy0`、`Wiphy phy1` | 两路 PHY 已识别；此时无线仍按上一步关闭 |
| UBI | `bad PEBs: 0, corrupted PEBs: 0` | 本次未报告坏/损坏块 |

最后在 SSH 执行 `reboot`，待有线恢复后重新用新密码登录，并再检查 `cat /proc/cmdline`。

**完成标准：能正常登录，仍是新系统，仍含 `ubi.mtd=rootfs_1`。** 本次已完成这个额外重启，并核对分区表、引导、校准和保留的原厂系统槽哈希与备份一致。

如需 Wi-Fi，在 LuCI“网络 → 无线”中为两路设置名称和 WPA2/WPA3 密码，然后启用、保存并应用。root 管理员密码与 Wi-Fi 密码分开管理。要测试上网还需接好 WAN 上游并按原有网络选择 DHCP/拨号；本次未测试 WAN 外网、吞吐或断电冷启动。

## 10. 本次常见问题速查

| 现象 | 判断与处理 |
| --- | --- |
| 网页能开，但电脑网线没通 | 网页可能走 Wi-Fi；检查正确网卡的 `Up`、有线 IP 和绑定该地址的 SSH |
| 网口灯不亮 | 检查软件链路状态并换口/换线；本次原厂 `swconfig dev switch1 show` 的对应端口最终为 `link:up speed:100baseT` |
| 后台 CR8806、底层 CR8808 | 本次就是这样；按底层主板、分区和目标定义交叉核对，不能凭后台名称选包 |
| 获取 root 第一组方法失败 | 看后续是否成功；本次 `connect5/smartcontroller` 成功。所有方法失败则停止 |
| SSH 密码认证失败 | 原厂后台密码、原厂 SSH 密码、新系统管理员密码是不同阶段的值；输入时不显示字符 |
| `Bad Gateway` / 502 | 本次是代理问题，使用 `curl.exe --noproxy "*"`；XMiR 进程设置 `NO_PROXY` |
| `sftp-server: not found` / SFTP 失败 | 原厂传文件使用 `scp.exe -O` |
| `sha256sum: not found` | 原厂使用 `openssl dgst -sha256`，不要跳过校验 |
| 备份校验报 `Missing backup` / `Backup length mismatch` | 物理分区缺失或截断，重新完整备份，不能继续生成刷写脚本 |
| 检查报 `Hash mismatch: /dev/mtd13` 等 | 当前分区与自己的备份不一致，可能选错备份/设备或状态已变化；核对并重新备份，不删除检查 |
| `Unfilled template` | 误传了模板。运行电脑上的准备脚本，上传 `tmp/prepared/flash-current-device.sh` |
| 新系统 XMiR 报密钥协商错误 | 旧内置 SSH 库不兼容新系统；新系统用 Windows 自带 `ssh.exe`，本次就是这样解决 |
| 首次启动暂时连不上 SSH | 等待初始化和有线 DHCP，先核对电脑是否获得 `192.168.1.x`，不要连续断电 |
| 新系统显示 Redmi AX3000 | 本次目标 `redmi_ax3000` 的正常显示，继续核对 `board_name`、版本及启动槽 |
| 重启回原厂页面 | 未达到完成标准。记录启动信息，按[恢复边界](cr8808-openwrt-flashing-research.md#7-失败与恢复边界)排查，不立即覆盖两个槽 |

## 11. 文件位置和验证范围

```text
C:\cr8808\
├── doc\cr8808-beginner-guide.md        本文
├── scripts\prepare-cr8808-flash.ps1    电脑上的备份校验/脚本生成工具
├── scripts\flash-cr8808-stock.template.sh
└── tmp\                              Git 忽略，本地材料
    ├── xmir-patcher-<固定提交>\
    │   ├── backups\                  自己的分区备份
    │   └── outdir\                   分区表等原始资料
    ├── firmware\                     固定镜像
    └── prepared\
        ├── backup-manifest.json       22 个物理备份的本地哈希
        ├── SHA256SUMS
        └── flash-current-device.sh    由自己的备份生成，不提交 Git
```

配套脚本：[电脑准备工具](../scripts/prepare-cr8808-flash.ps1)、[刷写模板](../scripts/flash-cr8808-stock.template.sh)。模板沿用本次成功的写入与数据页读回流程，新增专用脚本生成、清晰的失败提示及检查模式；生成器已用实机备份在 PowerShell 5.1 中验证，并检查了错误布局、缺失/截断备份及未填模板的拒绝行为。没有为编写教程重新刷写设备。

实机执行的原始步骤和结果见[实操记录](cr8808-openwrt-hands-on.md)，候选项目、其他硬件分流和恢复资料见[完整调研](cr8808-openwrt-flashing-research.md)。关于按住 Reset 上电后通过浏览器救援的功能，见[网页恢复 U-Boot 项目与本机支持判断](cr8808-web-uboot-research.md)：本次没有更换原厂 U-Boot，现有候选包也尚未完成本机适配验证。

备份、身份数据、密码和原始日志留在本地。GitHub 保存教程与脚本源代码，以及后续按用户要求整理、标记为待验证的[历史 WebUBoot 候选包](../firmware/webuboot/cr880x-20221214/README.md)；该候选包不属于本教程已验证的安装步骤。
