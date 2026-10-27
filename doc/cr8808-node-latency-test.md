# CR8808 节点可用性与延迟检测

检测日期：2026-10-27。本次先测全部 42 个节点，再对初测较快的 5 个节点各复测 3 次。完整节点名称和结果只保存在本机受限目录，仓库记录方法与汇总。

## 1. 本次结果

| 最终分类 | 数量 | 含义 |
| --- | --- | --- |
| 主目标通过 | 24 | 初测或最新复测成功；其中 3 个节点复测 3/3 成功 |
| 复测有失败 | 2 | 初测成功，随后各 3 次复测中均为 2 次成功、1 次失败 |
| 仅备用目标通过 | 2 | gstatic 探测失败，Cloudflare 探测成功 |
| 本轮未通过 | 14 | 两个目标均失败，包括 12 个 Hysteria2 和 2 个 VLESS |

首轮原始分类为 26 个主目标通过、2 个仅备用通过、14 个未通过。复测后，将其中两个有失败样本的节点单独分类。三次全部成功的候选中位延迟为 **363、454、540 ms**；对应名称、全部样本和筛选表见本地报告。

- 合并报告：`tmp/router-config/private/node-tests-20261027-final/results.html`，支持名称/协议筛选、结果筛选和延迟排序。
- 同目录：`results.json`、`results.csv`，含每个节点的状态、目标和样本数。
- 首轮：`private/node-tests-20261027/`；五节点复测：`private/node-tests-20261027-top5-retest/`，路径均相对于 `tmp/router-config/`。
- 检测前备份：`private/cr8808-before-node-tests-20261027.tar.gz`，SHA256 为 `2dc9ed09c4864513890ed6c2512301c80e0c04914a715c406a10ddc496c85c15`。

检测完成后已检查：临时绕过规则数为 0，路由器运行配置哈希与代理核心 PID 均与检测前一致，OOM 计数无新增。本次依据结果筛选候选，家庭主节点仍使用原配置。

## 2. 测的是什么

这版 HomeProxy 的自动选择功能可以在已勾选的候选中做 URLTest，但没有逐节点延迟列表。本机原来只勾选了 3 个候选，不能据此判断全部 42 个节点。

本机联网后可用内存较少，因此本次使用电脑上的官方 Windows sing-box `1.12.25`，从原生 HomeProxy 生成器导出节点，逐个经过当前家庭宽带连接。Windows 核心与路由器 tiny 核心版本相同、构建不同；结果用于筛选候选，所选节点仍需在 CR8808 上验证实际业务。

检测期间，仅对电脑当前的 IPv4 地址临时绕过路由器透明代理，让检测连接直接经 WAN 出站，避免通过现有节点再连接待测节点。两条临时规则分别覆盖 TCP 和 UDP，并配置 15 分钟自动清理；实际检测结束后已立即撤销。未修改持久防火墙配置。

主目标为 `https://www.gstatic.com/generate_204`，失败时再试 `https://www.cloudflare.com/cdn-cgi/trace`。sing-box URLTest 经指定节点建立连接并发起 HTTPS HEAD 请求，取得响应后记录延迟；该版本不检查是否恰好返回 HTTP 204。[默认目标说明](https://sing-box.sagernet.org/configuration/outbound/urltest/)、[1.12.25 实现](https://github.com/SagerNet/sing-box/blob/v1.12.25/common/urltest/urltest.go)。

延迟是该实现的 HTTPS 探测耗时，部分传输有不同计时点，不能直接当作 ICMP Ping、带宽或跨协议的严格性能比较。成功不代表服务解锁或长期稳定，失败也可能与测试目标、认证、DNS、UDP 路径或临时网络状态有关。本次没有进一步定位 14 个失败节点的具体原因。

## 3. 使用哪些脚本

| 脚本 | 作用 |
| --- | --- |
| [export-homeproxy-test-nodes.uc](../scripts/export-homeproxy-test-nodes.uc) | 调用现有生成器导出 VLESS/Hysteria2 节点和名称映射，只写临时导出文件 |
| [homeproxy-test-bypass.sh](../scripts/homeproxy-test-bypass.sh) | 按电脑单个 IPv4 和唯一标签添加、检查、移除临时透明代理例外，提供清理 watchdog |
| [test-homeproxy-nodes.py](../scripts/test-homeproxy-nodes.py) | 在电脑串行检测，生成 HTML/JSON/CSV，可按节点 ID 复测并计算成功样本中位数 |

导出、临时核心配置及日志含节点信息，使用项目已有受限目录 `tmp/router-config/private/`。Python 检测工具退出时清理临时核心配置并终止电脑上的检测核心。检测结果和凭据导出均不纳入 Git。

## 4. 在这台电脑重新检测

电脑保持连接 CR8808 的 LAN。先核对当前 IPv4 地址；下面的 `192.168.1.214` 是本次实测地址，变化后必须替换。

### 准备电脑核心

本次使用 [SagerNet 官方 1.12.25 发行版](https://github.com/SagerNet/sing-box/releases/tag/v1.12.25)的 `sing-box-1.12.25-windows-amd64.zip`。官方资产 SHA256 为 `492df6eb97c4c749d45350d792ecece71278d83c4979149ba6a142765b8fc1d4`，本机下载已核对。提取出的 `sing-box.exe` 保存为 `tmp/router-config/tools/sing-box-1.12.25-windows-amd64.exe`，SHA256 为 `fc7b65219abe8a0166d0b4891a2f7cabcbcc13b3adcf89e6d5913743a67aba10`。[官方资产清单](https://github.com/SagerNet/sing-box/releases/expanded_assets/v1.12.25)。

### 导出当前订阅节点

在项目根目录的 PowerShell 中执行；SSH/SCP 使用当前 root 管理员密码。`-O` 是这台设备所需的传统 SCP 模式。

```powershell
scp -O .\scripts\export-homeproxy-test-nodes.uc root@192.168.1.1:/tmp/
scp -O .\scripts\homeproxy-test-bypass.sh root@192.168.1.1:/tmp/
ssh root@192.168.1.1 'umask 077; ucode -L /etc/homeproxy/scripts -S /tmp/export-homeproxy-test-nodes.uc'
scp -O root@192.168.1.1:/tmp/cr8808-node-export/nodes.json .\tmp\router-config\private\node-test-nodes.json
scp -O root@192.168.1.1:/tmp/cr8808-node-export/labels.json .\tmp\router-config\private\node-test-labels.json
```

导出脚本核对已知生成器结构，保持当前运行配置文件不变。当前覆盖 VLESS 和 Hysteria2；其他协议会被检测工具列为未导出/不支持。

### 临时绕过测试电脑并执行检测

每次使用新的标签，避免旧 watchdog 干扰下一轮。`--output` 指向一个新的目录；检测工具拒绝覆盖已有报告目录。

```powershell
$NodeTestPcIp = '192.168.1.214'
$NodeTestTag = 'cr8808-node-test-' + [guid]::NewGuid().ToString('N')
$NodeTestOutput = '.\tmp\router-config\private\node-tests-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
ssh root@192.168.1.1 "sh /tmp/homeproxy-test-bypass.sh watchdog $NodeTestPcIp $NodeTestTag </dev/null >/tmp/cr8808-node-test-watchdog.log 2>&1 &"
if ($LASTEXITCODE -ne 0) { throw '无法启动临时规则清理 watchdog' }
try {
    ssh root@192.168.1.1 "sh /tmp/homeproxy-test-bypass.sh add $NodeTestPcIp $NodeTestTag"
    if ($LASTEXITCODE -ne 0) { throw '无法设置测试电脑的临时绕过规则' }
    python .\scripts\test-homeproxy-nodes.py `
        --core .\tmp\router-config\tools\sing-box-1.12.25-windows-amd64.exe `
        --nodes .\tmp\router-config\private\node-test-nodes.json `
        --labels .\tmp\router-config\private\node-test-labels.json `
        --source-ip $NodeTestPcIp --output $NodeTestOutput
    if ($LASTEXITCODE -ne 0) { throw '检测未完整结束，请查看报告和本机受限日志' }
} finally {
    ssh root@192.168.1.1 "sh /tmp/homeproxy-test-bypass.sh remove $NodeTestPcIp $NodeTestTag"
    ssh root@192.168.1.1 "sh /tmp/homeproxy-test-bypass.sh status $NodeTestPcIp $NodeTestTag"
}
```

最后的 `status` 应无匹配规则输出。中途退出时，先确认临时规则已清理；watchdog 提供超时清理。报告中的待测条目表示检测尚未执行，不能算作失败。

选少量节点复测时，在同样的临时绕过保护下添加 `--only-id 节点ID --samples 3`，可重复指定 `--only-id`。ID 从私有报告 JSON 或 CSV 读取。连续多次探测同一目标，报告显示成功样本数；任一次失败都会单独标记，延迟列取成功样本中位数。

## 5. 怎样使用结果

先在本地报告中筛选主目标通过的节点，再优先考虑多次复测全部成功、延迟适合实际业务的候选。仅备用目标通过的节点需要针对实际常用站点再试。

在 LuCI 的“服务 → HomeProxy → 客户端设置”中，主节点可选择单个节点，或使用自动选择并勾选候选。保存应用后，用家庭终端访问常用站点；实际代理出口、UDP 应用、带宽和持续负载属于后续验收项目。更新订阅后应重新导出、检测，避免沿用已经变化的节点 ID 与结果。
