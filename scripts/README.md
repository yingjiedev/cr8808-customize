# CR8808 定制脚本

这些脚本对应[主路由配置手册](../doc/cr8808-main-router-configuration-manual.md)中的 HomeProxy + sing-box 压缩挂载方案。已验证环境为本机 CR8808、ImmortalWrt `24.10-SNAPSHOT r0-9a11bb8`、内核 `6.6.137`。

## 文件与用途

| 文件 | 用途 |
| --- | --- |
| `build-sing-box-squashfs-ipk.py` | 校验输入哈希，打包包含压缩应用镜像、挂载服务及占位入口的 IPK |
| `sing-box-squashfs/etc/init.d/sing-box-squashfs` | 开机校验镜像/内核，进行只读 loop 挂载和可执行文件 bind mount |
| `sing-box-squashfs/usr/bin/sing-box` | 挂载前的占位入口，准备挂载后执行真正的内核 |
| `patch-homeproxy-init.py` | 为固定版本 HomeProxy 添加 Go 内存参数和条件 TUN 清理，支持重复执行 |
| `patch-homeproxy-rpc.py` | 对经校验的固定压缩内核直接返回版本与功能，避免页面查询额外启动 Go 进程 |
| `patch-homeproxy-node-ui.py` | 校验固定原文件并生成节点页、RPC 与同核心测速配置补丁 |
| `homeproxy-low-memory/` | 按需测速的生成器、RPC、轻量本机请求 worker 与前端片段 |
| `cr8808-proxy-wan.init` | 依据 WAN 状态及 `homeproxy.config.cr8808_autostart` 控制代理启动 |
| `cr8808-proxy-wan.hotplug` | 响应 WAN `ifup` / `ifdown` 事件 |
| `export-homeproxy-test-nodes.uc` | 从本机 HomeProxy 生成器导出节点到临时私有文件，保持运行配置 |
| `homeproxy-test-bypass.sh` | 为测试电脑临时绕过 TCP/UDP 透明代理，按唯一标签清理并提供 watchdog |
| `test-homeproxy-nodes.py` | 电脑端串行 HTTPS 延迟检测、按 ID 复测及 HTML/JSON/CSV 报告 |

其他已有刷机、候选 WebUBoot 检查脚本的说明仍以相应专项手册为准。

## 本地构建

Python 工具只使用标准库。先准备经过校验的原始 `sing-box-tiny` IPK、提取出的 ELF，以及通过 `gensquashfs` 创建的应用镜像。原始下载来源及校验值见配置手册；工具、下载文件和构建输出放在 Git 忽略的 `tmp/`。

初次 r2 镜像使用 squashfs-tools-ng `1.3.2` 生成，压缩方式为 XZ，块大小为 1 MiB；当前 r3 使用相同 ELF、64 KiB 块，见[资源优化手册](../doc/cr8808-low-memory-homeproxy.md)。下面保留初次构建示例，构建 r3 时使用新镜像路径/哈希及版本。打包列表如下，源文件路径相对于列表文件：

```text
file /sing-box 0755 0 0 sing-box-tiny
```

Windows PowerShell 构建本次使用的 r2 IPK：

```powershell
python .\scripts\build-sing-box-squashfs-ipk.py `
  --image .\tmp\router-config\research\sing-box-core.squashfs `
  --image-sha256 62e279ef5795bf546112530e73537495d1d0ef6d87fc4c86d35f8acff0e45da5 `
  --binary .\tmp\router-config\research\sing-box-tiny `
  --binary-sha256 c3faeded3104bf8c581d2050b5786425b8a7862cea42c1ae19f0e2b98d582af5 `
  --source-package .\tmp\router-config\research\sing-box-tiny_1.12.25-r1_aarch64_cortex-a53.ipk `
  --source-package-sha256 bdd93e62ef2d4351fa9a5f9e8a8b6101e7178b0343853e1705bf2ef08b3e5a6d `
  --version 1.12.25-r2 `
  --output .\tmp\router-config\packages\sing-box-squashfs_1.12.25-r2_aarch64_cortex-a53.ipk
```

构建只生成本地文件；安装 IPK 会写入系统并启用挂载服务。其安装检查仅核对板名、已有内核归属和基本挂载能力，不代替固件/分区适配验证。

## HomeProxy 补丁

先取得本机安装的原始 `/etc/init.d/homeproxy`，保留原件，然后在电脑执行：

```powershell
python .\scripts\patch-homeproxy-init.py `
  .\tmp\homeproxy.original.init .\tmp\homeproxy.patched.init
```

脚本针对 HomeProxy `26.236.50592~9b8ee64` 的已知代码结构。匹配结构不符时退出；新版本应重新核对，不能强行替换。生成的文件需在路由器上用 `sh -n` 检查，再安装为 `/etc/init.d/homeproxy` 并设置执行权限。

当前 GFWList 配置在上述命令添加 `--gogc 100`；脚本同时给配置检查进程设置内存参数。默认仍为初次配置的 `GOGC=50`。支持对同一输出再次执行，不重复插入环境参数。

本机联网后还需应用 RPC 补丁。先保存路由器原始 `/usr/share/rpcd/ucode/luci.homeproxy`，然后在电脑生成补丁文件：

```powershell
python .\scripts\patch-homeproxy-rpc.py `
  .\tmp\luci.homeproxy.original .\tmp\luci.homeproxy.patched
```

补丁只在两个路径指向同一份已挂载 ELF、文件长度吻合，且包清单记录的 ELF SHA256 与本次固定内核一致时使用预先核对的版本及功能列表。内核模块能力仍实时检测；其他内核保留 HomeProxy 原来的查询方式。初次安装时核对本机内核哈希和功能来源，不从其他版本复制功能列表。

将结果先上传路由器 `/tmp`，执行 `ucode -c -o /tmp/homeproxy-rpc-check.bin /tmp/luci.homeproxy.patched` 检查语法，再以 `0644` 权限安装到 `/usr/share/rpcd/ucode/luci.homeproxy`，执行 `/etc/init.d/rpcd restart` 加载。该操作可能需要重新登录管理页。保留原件用于回滚；升级 HomeProxy 后需重新核对并应用适配。

WAN 事件脚本在本机分别安装为 `/etc/init.d/cr8808-proxy-wan`、`/etc/hotplug.d/iface/95-cr8808-proxy-wan`；具体启停与验收步骤见配置手册。

仓库保存可复用脚本和脱敏手册。凭据、节点配置、设备备份、一次性登录控制工具及下载的二进制保存在本机忽略目录。

节点检测的核心校验、导出、临时规则及完整运行步骤见[节点可用性与延迟检测](../doc/cr8808-node-latency-test.md)。电脑端检测使用同版本原生核心，并需让该电脑的测试连接直接经家庭 WAN 出站；启用前核对当前电脑 IPv4，完成后检查临时规则已清理。

当前节点页按钮直接复用路由器核心，使用另一条按需路径，不需要临时绕过电脑。补丁构建、部署、串行限制与版本边界见[资源优化手册](../doc/cr8808-low-memory-homeproxy.md)。前端行为测试：`node --test tests/homeproxy-node-ui.test.cjs`。
