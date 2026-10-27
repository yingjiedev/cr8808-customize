# CR8808 资源优化、网站分流与节点页测速

日期：2026-10-27。适用本机 ImmortalWrt `24.10-SNAPSHOT r0-9a11bb8`、HomeProxy `26.236.50592~9b8ee64`、sing-box tiny `1.12.25`。

## 分流策略

按用户选择，将 `homeproxy.config.routing_mode` 从 `bypass_mainland_china` 改为 `gfwlist`。保留用户当前选中的主节点、TCP redirect / UDP tproxy、Wi-Fi 与 WAN DHCP 配置。

GFWList 中的域名交给代理 DNS 解析，dnsmasq 把结果加入 nftables 集合，再由透明代理接管这些目标地址。其他网站默认直连。主内核因此不再加载原模式的三份中国 IP/国内域名/海外域名规则集与规则缓存数据库。

这实现了按网站选择出口的需求，家庭终端不必单独设置浏览器 PAC。严格说，PAC 是浏览器执行的 `FindProxyForURL()` 脚本，本机没有新增 `.pac` 下载服务。[PAC 定义](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Proxy_servers_and_tunneling/Proxy_Auto-Configuration_PAC_file)。

在“服务 → HomeProxy → 客户端设置 → 路由设置”查看 GFWList 模式；在“访问控制”页的代理列表中补充需要代理的域名，保存应用。名单外海外网站默认直连，因此不保证全部海外业务可用。该固件的自定义列表由域名生成 DNS/nftables 规则，按域名填写，不填写完整网址路径。

GFWList 依赖终端通过路由器 DNS 建立域名与 IP 的关联。应用自己的 DoH、切换模式前的 DNS 缓存及共用 CDN 地址会影响判断；需要一致分流时，让终端使用 `192.168.1.1` 解析，并在切换后刷新终端 DNS 缓存。它不能按加密 HTTPS 的网址路径分流。

## 资源调整

- 停止加载原模式的三份远程规则集，并清理本模式不用的旧规则缓存数据库；保留正常 DNS 缓存，将 sing-box 的 DNS 缓存容量设为 256。
- 保留 `GOMEMLIMIT=24MiB`，将本模式的 `GOGC` 调为 100，减少不必要的频繁回收。配置检查进程也使用相同参数。内存限制是 Go 的软目标，不是整个进程 RSS 的硬上限。[Go GC 与内存限制](https://go.dev/doc/gc-guide)。
- 同一份经过校验的 ELF 改用 64 KiB XZ 压缩块，原来为 1 MiB，降低随机读页的解压粒度。镜像增加 962,560 字节，二进制本身未修改。
- 保留已安装的功能查询缓存补丁，打开 LuCI 页面不启动第二个 Go 进程。测速也复用正在运行的核心。

内存应观察 `/proc/meminfo` 的 `MemAvailable` 与进程 `VmRSS` / `RssAnon`；Go 预留的约 1.2 GiB `VSZ` 不是实际占用。本机两路 CPU 的负载、忙碌比例和瞬时峰值也不能相互等同。

### r3 压缩核心

| 项目 | 值 |
| --- | --- |
| 包版本 | `sing-box-squashfs 1.12.25-r3` |
| ELF SHA256 | `c3faeded3104bf8c581d2050b5786425b8a7862cea42c1ae19f0e2b98d582af5` |
| ELF 字节数 | 29,688,696 |
| SquashFS 字节数 | 8,650,752 |
| SquashFS SHA256 | `53675e18be3838bd190e63ba4da5480c8aa5ce6459f38c6b950fd1e166594c2c` |
| IPK SHA256 | `4e8bb53e19fe7c17da67828907edcd6a624b7797b7185dff3f492d8439a03af6` |

在原核心文件与清单所在目录执行 `gensquashfs -c xz -b 65536 -F sing-box-core.list sing-box-core-xz-64k.squashfs`，再使用仓库的 `build-sing-box-squashfs-ipk.py`，参数与初始手册一致，但替换镜像路径、镜像哈希、版本为 `1.12.25-r3`。已用 `rdsquashfs -c /sing-box` 提取核对 ELF 哈希。

本机 opkg 升级时按完整包大小检查剩余空间，首次检查拒绝安装。已核算镜像净增长不足 1 MiB，而升级前余量约 4 MiB，另保留 2 MiB 余量；本次才使用 `opkg --force-space install` 完成升级。不要把这个参数用于空间不足或未核算的新版本。旧 r2 IPK 与设备配置备份留在电脑上，恢复包不含整机固件。

## 节点页面如何测速

打开 [HomeProxy 节点页](http://192.168.1.1/cgi-bin/luci/admin/services/homeproxy/node)，每个节点增加“HTTPS 延迟 / 测试延迟”按钮。更新后首次用 `Ctrl+F5` 刷新，必要时重新登录。

1. 导入或修改节点后，先保存并应用。
2. 点击一个节点的“测试延迟”。等待返回 `xxx ms · 重测` 或“本次未通过 · 重测”。
3. 再点击下一个节点；不自动轮询全部节点，也不自动切换家庭主节点。

该补丁当前覆盖 VLESS / Hysteria2，最多登记 64 个符合基本字段要求的节点；本机 42 个全部登记。其他协议、未应用的新节点或已更改但未重新加载的节点会提示先应用，不能据此判断节点已失效。大量节点会增加配置和常驻对象的占用，因此设了数量上限。

经该路由器指定节点对 `https://www.gstatic.com/generate_204` 执行 sing-box 原生 HTTPS HEAD 探测，超时 5 秒；与之前电脑端的备用目标测试不同，本按钮只测这个目标。它验证了一次真实代理请求，不是 ICMP Ping、带宽测试或服务解锁测试。该版本的原生实现不要求 HTTP 状态恰好为 204。[原生 URLTest](https://github.com/SagerNet/sing-box/blob/v1.12.25/common/urltest/urltest.go)、[逐节点 delay API](https://github.com/SagerNet/sing-box/blob/v1.12.25/experimental/clashapi/proxies.go)。

### 开销与边界

- 页面打开不发起测速或定时状态查询。只有点击后，浏览器才约每秒读取当前任务状态，结束即停止。
- 不新增常驻服务，不启动第二个 sing-box；核心保留候选节点对象，未选中节点不加入自动 URLTest。
- 后端全局任务锁约束多标签页；一次只有一个按钮任务。HTTPS 探测限制为 5 秒，本机请求由 ucode 原生 `system()` 的 10 秒期限终止；使用 `exec` 执行固件现有的最小 BusyBox `nc`，不加载下载工具的 TLS 库。该固件没有 `timeout` 命令，`nc` 也不支持 `-w`。任务异常后可在 20 秒后重试。
- `MemAvailable` 低于 10 MiB 时拒绝开始新的检测。该保护不代替负载测试，测速及实际网络活动仍会产生短时 CPU/内存变化。
- 结果只在 `/var/run/homeproxy/` 保存最近 8 个小文件，重启清除，不写闪存。页面刷新后按钮恢复初始文字。
- 控制接口只监听 `127.0.0.1:9091`，随机密钥留在 root 私有文件；通过现有 LuCI 登录和 RPC 转发访问。没有额外的管理面板或面板资源下载。
- 原有自动选择候选若继续使用，仍会按其周期探测；页面的串行锁约束手动任务，不阻止核心原有自动选择。

## 可复用文件与部署

| 文件 | 用途 |
| --- | --- |
| `scripts/patch-homeproxy-node-ui.py` | 验证固定版本的三个原文件哈希，生成节点页、配置生成器和 RPC 补丁 |
| `scripts/homeproxy-low-memory/generator.uc` | 向同一个核心加入未选中的测速节点对象、私有控制接口与 DNS 缓存上限 |
| `scripts/homeproxy-low-memory/rpc.uc` | 输入校验、已应用配置指纹、内存检查、全局任务锁、任务状态 |
| `scripts/homeproxy-low-memory/worker.uc` | 短时执行本地请求，保存脱敏结果并清理任务锁 |
| `scripts/homeproxy-low-memory/ui.js` | 点击按钮、串行限制、有限轮询和结果文字 |
| `scripts/patch-homeproxy-init.py --gogc 100` | 为本模式生成 init 内存参数及配置检查参数 |

补丁生成器要求原始 `generate_client.uc`、原始 `node.js`，以及已经应用压缩内核功能缓存补丁的 `luci.homeproxy`。任一哈希不符就停止，不能向 HomeProxy 新版本强行套用。

```powershell
python .\scripts\patch-homeproxy-node-ui.py `
  --generator .\tmp\generate_client.original.uc `
  --rpc .\tmp\luci.homeproxy.cached.uc `
  --node-js .\tmp\node.original.js `
  --output .\tmp\homeproxy-node-ui
```

先备份设备配置与将被覆盖的文件，生成后上传 `/tmp`。用 `ucode -L /etc/homeproxy/scripts -c -o /tmp/check.bin /tmp/generate_client.uc`、`ucode -c` 分别检查 RPC 和 worker，用 `sh -n` 检查 init。电脑还可用同版本核心校验协议参数；安装后仍须做设备验收。

在路由器创建密钥，不在聊天、Git 或日志中显示：

```sh
umask 077
if [ ! -s /etc/homeproxy/node-test.secret ]; then
  { cat /proc/sys/kernel/random/uuid; cat /proc/sys/kernel/random/uuid; } |
    tr -d '\n-' > /etc/homeproxy/node-test.secret
fi
chmod 600 /etc/homeproxy/node-test.secret
```

安装路径为 `/etc/homeproxy/scripts/generate_client.uc`（0755）、`/etc/homeproxy/scripts/cr8808-node-test-worker.uc`（0700）、`/usr/share/rpcd/ucode/luci.homeproxy`（0644）、`/www/luci-static/resources/view/homeproxy/node.js`（0644）及 `/etc/init.d/homeproxy`（0755）。生成器把含凭据的运行配置设为 `root:sing-box 0640`，节点索引和任务结果为 0600。

选择 `gfwlist`，提交 UCI 配置，再重启 rpcd 与 HomeProxy 使补丁生效。升级 HomeProxy 会覆盖补丁；恢复或升级后需要重新核对版本、密钥和三个文件的适配。恢复时使用私有备份的配置和原文件，删除新增 worker 与密钥，再重启服务；需要恢复 r2 核心时，使用本机保存并校验的旧 IPK。

## 本次验证记录

配置变更前备份：`tmp/router-config/private/cr8808-before-optimization-20261027.tar.gz`，SHA256 `01fbfbfd1971a06d596cb428215fb222d93ad3278a5a6a6fffb676663ae440d5`，电脑备份目录另有副本。

当前配置及补丁快照：`private/cr8808-optimized-homeproxy-20261027.tar.gz`，SHA256 `33d8cd9ce7934e61ae4ccef92f4e0eeaa4972ee77e8eb0507e59a682ebe32706`。离线恢复包为 `private/cr8808-homeproxy-gfw-node-test-restore-20261027.zip`，包括匹配依赖、r3 IPK、当前快照、基线源码及回滚用 r2/旧快照；第二份保存在 `C:\Users\yingj\cr8808-backups\2026-10-27-main-router\`。这些文件含配置凭据，不提交 Git。校验记录为 `evidence/homeproxy-optimization-restore-bundle.json`，路径均相对于 `tmp/router-config/`。

初始采样 `MemAvailable` 为 14,608 KiB、代理匿名内存 15,764 KiB；切到 GFWList 后匿名内存约 6,592 KiB。实际数字受家庭流量、页缓存及采样时机影响，不是固定上限或同负载性能对比。

最后一次 30 秒窗口：`MemAvailable` 为 20,748–29,916 KiB，代理 RSS 约 23,340 KiB、匿名内存约 8,796 KiB。两路 CPU 总计时器计算的系统平均忙碌约 **0.98%**；代理约占 **0.30% 单核**。这是当时空闲/轻负载状态，不能当作持续代理负载或测速时的 CPU 上限。测速与家庭流量期间另观察到可用内存约 18 MiB，r3 刚启动时则约 32 MiB。

轻量 worker 本身观测约 1.1 MiB RSS；它与最小 nc 的许多映射和既有进程共享，不能把多个 RSS 简单相加当作新增物理内存。设备先后返回 1138 ms、400 ms 的成功样本，并验证 Hysteria2 失败样本、并发请求返回 `busy`、临时进程和锁退出。代理核心 PID 在测速期间不变，OOM 记录仍只有之前页面修复前的 1 次。用户已在实际浏览器确认按钮显示与结果正常。

前端行为测试使用 `node --test tests/homeproxy-node-ui.test.cjs`，覆盖页面打开无请求、两次点击仅发起一个任务、低内存拒绝后可再点、失败样本可重试。还在原生 ucode 检查语法、非法节点 ID/任务 ID 拒绝、未应用节点提示，并在设备上检查全局忙碌锁。完整节点结果、核心配置、凭据与设备备份只保存在本机私有目录。
