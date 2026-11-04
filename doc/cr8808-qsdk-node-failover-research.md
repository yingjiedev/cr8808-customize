# QSDK PassWall2 节点故障切换与资源开销调研

日期：2026-11-02。范围是现有 CR8808 的 PassWall2 26.10.29 / Xray 26.10.31 固定版本。以下记录最初的源码核查与方案比较；用户随后选定双节点、30 分钟间隔、单个 Xray，已按文末的部署记录应用。

## 结论与调研开始时的状态

当前应用支持故障自动切换，调研开始时的配置尚未启用。2026-11-01 晚保存的实际 Xray 配置没有 `observatory`、`burstObservatory` 或路由 `balancers`，只包含一个 Hysteria 代理出站。这是调研阶段采用的配置快照；部署前已重新登录读取实际状态。首页 Google 检测成功与否，本身不会让固定节点自动更换。

以减少新增进程和服务重启为目标，优先使用现有 Xray 进程内的连接观测和负载均衡组件。实用方案是两个独立候选节点、`leastPing`、60 秒探测间隔；严格减少探测次数时，可以只观测一个主节点，并把第二个节点设为 `fallback_node`。

这两种方案都能用当前版本表达，不要求升级 firewall4、换固件或安装第二个代理内核。候选使用 Xray 原生支持的节点类型，并关闭不需要的链式代理，才能保持单个代理内核进程；混入其他内核的节点可能让生成器另起 SOCKS 转接进程。

## 核查依据

锁定版本见 [源码锁](../firmware/qsdk/proxy/source-lock.json)：

- PassWall2：`d08e7f88fcb5c7f94b870f7281db0045a0477293`。
- Xray：`a4a3dff5b20c2faae567b742c172c7b95e75c083`。

已读取对应固定提交的上游文件，并与本机相同版本源码的关键分支对照：

| 证据 | 核查结果 |
| --- | --- |
| [PassWall2 Xray 界面](https://github.com/Openwrt-Passwall/openwrt-passwall2/blob/d08e7f88fcb5c7f94b870f7281db0045a0477293/luci-app-passwall2/luasrc/model/cbi/passwall2/client/type/2_xray.lua#L79) | 支持 `_balancing`、手动候选、`leastPing`、`leastLoad`、备用节点、自定义探测 URL 和探测间隔。 |
| [PassWall2 Xray 配置生成器](https://github.com/Openwrt-Passwall/openwrt-passwall2/blob/d08e7f88fcb5c7f94b870f7281db0045a0477293/luci-app-passwall2/luasrc/passwall2/util_xray.lua#L1130) | 生成实际出站、balancer 和观测组件；普通观测当前固定 `enableConcurrency=true`，界面没有单独的串行开关。 |
| [Xray leastPing](https://github.com/XTLS/Xray-core/blob/a4a3dff5b20c2faae567b742c172c7b95e75c083/app/router/strategy_leastping.go#L30) | 从观测为存活的候选中选择延迟最低者；不会根据配置列表顺序实现主节点优先。 |
| [Xray 路由回退](https://github.com/XTLS/Xray-core/blob/a4a3dff5b20c2faae567b742c172c7b95e75c083/app/router/balancing.go#L95) | 候选没有可选结果时使用 `fallbackTag`。 |
| [PassWall2 SOCKS 自动切换](https://github.com/Openwrt-Passwall/openwrt-passwall2/blob/d08e7f88fcb5c7f94b870f7281db0045a0477293/luci-app-passwall2/root/usr/share/passwall2/socks_auto_switch.sh#L43) | 有主备切换、网络连通性辅助判断和可选恢复主节点；测试备用节点会临时启动代理实例。 |

此前空闲实测总 CPU 平均约 8.47%，`MemAvailable` 最低 27,048 KiB；下载观测中最低 26,516 KiB。当前更应控制额外内核实例及测试期间的内存峰值。上述数值是此前采样，并非本轮实时测量。

## 方案比较

| 方案 | 新增进程及探测特点 | 行为与适用性 |
| --- | --- | --- |
| 单个 Xray，两个候选，`leastPing` | 不新增代理内核进程；健康状态下每轮约两次小型 HTTPS 请求。 | 两个节点都接受检测，新连接选择当前健康且延迟较低者。适合本机先实施验证。 |
| 单个 Xray，一个受观测的主节点，另一个作为 fallback | 不新增代理内核进程；正常时每轮约一次小型 HTTPS 请求。 | 优先主节点，故障后使用备用；备用不在观测选择器内，不能提前发现其失效；主节点恢复后，新连接会自动返回主节点。 |
| PassWall2 SOCKS 自动切换 | 为本机现有透明代理再增加 SOCKS 服务、常驻 shell 检测及短时 curl；测试备用会临时起内核。 | 有明确主备与可选回切，但不能仅勾选 SOCKS 自动切换就假定原透明代理自动跟随，还需正确接入该 SOCKS 出站。内存峰值需特别验证。 |
| 自编 shell 监控并更改节点 | 常驻部分可以很小；探测、备用验证、配置生成及重启仍有开销。 | 可定制连续失败阈值、冷却和恢复策略，但要新增维护逻辑；重启整个代理会影响已有连接，不能仅根据脚本大小认定总资源更低。 |

`leastLoad` 也是单进程能力，但它使用 `burstObservatory` 的历史采样和稳定性策略。固定生成器设 `sampling=3`、`timeout=5s`；采样窗口会影响故障发现时间。它不是简单的“主节点失败就切备用”。也不能把 sampling=3 解读为每个 interval 一定探测三次；平均探测密度与整个采样窗口的关系见 [Xray 连接观测文档](https://xtls.github.io/config/observatory.html#pingconfigobject)。当前没有证据证明它在本机的 CPU 或内存优于普通观测。

## 两种单进程配置草案

实用方案是在 PassWall2 节点列表添加 Xray 的“负载均衡”虚拟节点，手动选两个候选，策略 `leastPing`，探测间隔 `1m`，URL 先用 `https://www.gstatic.com/generate_204`。它发送的是连通性小请求，并非带宽测速。

以下仅是待填入真实节点 ID 的配置草案，不是可以直接执行的部署脚本：

```uci
config nodes 'cr8808_auto'
	option remarks 'CR8808 Auto'
	option type 'Xray'
	option protocol '_balancing'
	option node_add_mode 'manual'
	list balancing_node 'PRIMARY_NODE_ID'
	list balancing_node 'BACKUP_NODE_ID'
	option balancingStrategy 'leastPing'
	option useCustomProbeUrl '1'
	option probeUrl 'https://www.gstatic.com/generate_204'
	option probeInterval '1m'
```

随后在现有 GFW 分流节点中，把需要代理的规则出口改为这个虚拟节点，继续保留国内默认直连。不要把整个 GFW 分流节点替换成均衡节点，否则可能改变国内流量路径。候选应按实际服务器和协议去重；同一个服务器的订阅别名不构成独立备用，异协议或异入口可以降低部分共同故障的风险，同一供应商的公共故障仍无法由此解决。

对两个候选都不可用的情况，此固定版本在未设置备用时实际生成 `fallbackTag=blackhole`。界面“关闭备用”不是省略 fallback 的原始 Xray 语义。验证时应核查生成结果。[固定生成器的备用分支](https://github.com/Openwrt-Passwall/openwrt-passwall2/blob/d08e7f88fcb5c7f94b870f7281db0045a0477293/luci-app-passwall2/luasrc/passwall2/util_xray.lua#L1173)

严格减少正常探测次数时，对上面的草案作两项调整：

```uci
# 候选列表只保留主节点，备用节点不同时加入候选列表。
list balancing_node 'PRIMARY_NODE_ID'
option fallback_node 'BACKUP_NODE_ID'
```

备用出站仍由同一 Xray 管理。当前生成器观测 `blc-` 前缀的候选出站，不主动观测这个普通 fallback 出站。因此这是减少探测而牺牲备用健康信息的方案。它也不提供“备用用得好就保持不回切”的滞回策略。

两候选、60 秒间隔，理想健康状态约两次探测/分钟；49 条订阅全部以 10 秒间隔检测，理想值可达 294 次/分钟。实际普通观测会等待该轮探测完成再休眠，故请求次数通常更少。减少候选和频率，比只调整选择算法更直接。[普通观测的调度实现](https://github.com/XTLS/Xray-core/blob/a4a3dff5b20c2faae567b742c172c7b95e75c083/app/observatory/observer.go#L64)

## 必须纳入验收的限制

1. **当前普通观测总超时固定为 5 秒。** Xray 的 `observer.go` 同时设置 5 秒 TLS 握手超时和 5 秒 HTTP Client 总超时。PassWall2 的这个界面没有暴露该参数。此前首页改成连接 8 秒、总计 12 秒，只作用于首页 curl，不会改变自动切换探测。此前部分成功连接超过 5 秒，说明对这些节点存在误判风险。[固定内核实现](https://github.com/XTLS/Xray-core/blob/a4a3dff5b20c2faae567b742c172c7b95e75c083/app/observatory/observer.go#L136)
2. **原生 leastPing 没有“连续两次失败才剔除、冷却五分钟”的配置。** 此版本直接以最近一次观测更新 Alive。若节点冷启动经常超过 5 秒，先更换更稳定候选和探测站点；仍不满足要求时，再评估内核的可追溯超时与防抖修改，或独立状态机。无需为了调整这一用户态功能升级 firewall4，但内核修改需要构建和验收。
3. **HTTPS 连通不等于完整业务可用。** 此普通观测源码只检查 HTTP 请求是否出错，没有要求响应状态必须为 204。因此请求能完成但返回 403 等结果时仍可能算存活；它也不能证明该节点的 UDP、特定网站或下载速率正常。选用可靠的 HTTPS 204 地址可以减少歧义，却不改变这个实现限制。
4. **切换主要影响新连接。** 既有 TCP 连接不能迁移到另一个服务器；故障时由应用重连。60 秒探测间隔意味着约一分钟量级的发现时间，还需加上该轮请求和超时；不能承诺瞬间或固定 60 秒完成切换。主备方案则会在观测主节点恢复后对新连接回切。[路由选择语义](https://xtls.github.io/config/routing.html#balancerobject)
5. **新增进程数为零不等于新增内存为零。** 第二个出站、TLS/QUIC 状态、探测协程及连接缓冲仍消耗内存。HY2 的收包窗口配置也不能直接当成即时 RSS 分配量。没有实机前后对照，不能承诺增加少于某个 MiB 或 CPU 小于 1%。`GOMEMLIMIT=32MiB` 是 Go 的软目标，不能当进程 RSS 硬限额。

## 实施前后的验收设计

实施时先重新读取实际配置和运行状态，备份后仅更改代理出口选择。保留已验证的证书指纹、GFW 直连策略及 NSS 转发链路。

- 在相同流量条件下分别记录固定节点基线、两个候选、单主 fallback 的 CPU 计时、Xray RSS/PSS（设备若支持）、MemAvailable、交换活动和进程数量；每组至少覆盖多个完整探测周期，观测启动及故障验证峰值。以实测比较资源，不能只根据配置体积判断。
- 对每个候选做指定出站的 HTTPS 检查，涵盖冷连接；不得通过最终自动出口检测某候选，否则可能被其他正常节点掩盖故障。
- 用隔离测试实例或严格限定为测试出站的故障注入，验证主故障、备用故障、恢复、全部失效。不能关闭 WAN 来代替单节点故障测试，也不能对共享服务器地址作全局屏蔽。
- 确认切换不重启整个 Xray，已有健康连接保持运行；同时检查国内下载直连和 NSS 计数继续增长。客户端是否续传还受应用本身影响。
- 订阅更新后复核候选引用，避免去重、节点重建或更名使虚拟节点指向已删除的条目。

上述调研阶段只有源码和配置快照核查，没有实施故障注入或资源 A/B 测量。初始建议优先验证“两节点、60 秒、同一 Xray”的方案；如果用户更重视最少探测次数，并接受无法提前确认备用健康，则可采用单主 fallback。随后用户明确选定 30 分钟间隔，实际按该要求部署。

## 用户选定方案的部署结果

2026-11-02，按用户选择将实际探测间隔设为 `30m`，保留两个候选和单个 Xray。策略采用 `leastPing`，它为新连接选择最近一次探测中健康且延迟较低的候选，不提供固定主备优先级。完整脱敏数据见 [实机验收记录](validation/qsdk-passwall2-failover-20261102.json)。

最终选定两个服务器地址不同的日本 Hysteria2 条目，两者标称倍率均为 0.1，证书指纹与 SNI 均精确保留。最初的 VLESS 候选虽通过启动小请求，后续访问有超时；另一 Hysteria2 候选启动探测出现 EOF，均未进入最终组合。后者失败时，剩余正常候选仍保持电脑与路由器 HTTPS 可用。

最终组合原生启动探测分别约 1.82 / 2.09 秒；试用阶段电脑 4 次、路由器 6 次 HTTPS 204 检查通过。关闭临时详细日志并恢复 `error` 等级、重新启动代理后，电脑与路由器各 4 次验证 TLS 的 HTTPS 204 检查再次通过。电脑请求绑定有线接口并使用路由器 DNS。运行配置和进程数均确认只有一个代理内核，系统没有重启；防火墙配置保持一致，WAN 与两个无线 AP 均正常，NSS/ECM 模块保留。

最终 30.25 秒、7 个样本中，总 CPU 平均约 4.78%，Xray RSS 为 36,352–36,916 KiB，可用内存最低 31,304 KiB。观察到 13 页交换读入，没有新增交换写出或 OOM。该短样本不是单节点/双节点受控资源 A/B 测量，也没有覆盖下一次 30 分钟周期或证明长期稳定性。

配置已持久化，变更前后 `/etc` 均有本机私有备份并验证 SHA256。验收回退计时器已接受并停止。未对最终组合做主动故障注入；原生 5 秒超时及原有 TCP 连接需要重连的限制仍然存在。
