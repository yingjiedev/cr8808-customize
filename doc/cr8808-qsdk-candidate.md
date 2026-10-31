# CR8808 QSDK NSS 候选构建

本分支从主分支建立，使用来源可追溯的 hzyitc QSDK 路线重新编译。目标是在现有 36 MiB 系统槽内准备具备 NSS/ECM、双频 Wi-Fi 和 LuCI 的候选，后续分别验收稳定性和普通 NAT 的持续 500 Mbps 性能余量。

**构建成功不等于本机验收通过。** 本流程只构建和检查产物，不连接路由器或执行刷写。实际家庭宽带下行为 300 Mbps、峰值约 350 Mbps；该线路的测速结果不能证明路由器具备 500 Mbps 转发能力。

## 来源和固定输入

- [上游原始发布，2024-07-27](https://github.com/hzyitc/openwrt-redmi-ax3000/releases/tag/ci-ipq50xx-qsdk-kernel-5.4-openwrt-21.02-qsdk-11.5.05.841.1029-20240727-173350-UTC)。用户提供的基础版镜像与该发布公布的完整 SHA256、附件大小一致。
- [上游源码提交 ab1f9ffa5b5b62f252a5e87eb23f51f4e2544511](https://github.com/hzyitc/openwrt-redmi-ax3000/commit/ab1f9ffa5b5b62f252a5e87eb23f51f4e2544511)。使用 OpenWrt 21.02.7 应用层、QSDK 11.5 内核及驱动，实际 Linux release 为 5.4.164，用户空间为 ARM32。
- 四个 feed 与原发布一致，固定完整提交 ID。使用 GitHub 上游镜像取得相同提交，拉取后再次核对 HEAD。
- 原发布的 `config.buildinfo`、`feeds.buildinfo`、`version.buildinfo` 和 `sha256sums` 保存在 [reference](../firmware/qsdk/reference)，前三项与原发布正文公布的 SHA256 对照。
- 原发布的 `dl.tar` 下载归档固定完整文件大小、SHA256，并附逐文件大小和 SHA256 清单。原发布没有公布 `dl.tar` 的摘要；本仓库的摘要从其 HTTPS 发布附件下载后计算，不能冒称为原作者发布的摘要。
- 上游 NSS 和无线固件配方原先指向浮动 `main`。本候选改用上述归档中的固定压缩包，并添加其 SHA256；内核、NSS 驱动、ECM、交换机驱动和生成的 backports 同样锁定归档摘要。固件归档的内容身份已固定，但没有据此虚构无法证明的原固件 Git 提交。

完整输入见 [source-lock.json](../firmware/qsdk/source-lock.json) 和 [source-cache-manifest.json](../firmware/qsdk/source-cache-manifest.json)。25 MiB、标称 `24.10-SNAPSHOT qsdk-nss` 的来源未明镜像没有作为构建输入。

## 首轮范围

| 项目 | 候选配置 |
| --- | --- |
| 设备 profile | `ipq50xx/arm` / `redmi_ax3000` / FIT `config@mp02.1` |
| 原有系统分区 | 保持原 36 MiB 单槽尺寸；候选 factory 上限 32 MiB |
| NAND | QSDK QPIC 驱动，ECC4/512；与本机已观测的 2048+64 NAND 相符 |
| CPU | 保持上游 1.008 GHz 上限 |
| 内存 | 256 MiB 配置；NSS 保留 8 MiB、Q6 保留 48 MiB |
| 有线 | QSDK nss-dp + swconfig；LAN 为 eth1 / 交换机 CPU 口 6，WAN 为 eth0 / CPU 口 5 |
| 加速 | NSS/ECM standard，显式选择 NSS，禁用同时启用的 fw3 软件 flow offload |
| 无线 | 上游 QSDK ath11k 和固定固件，保留上游无线 NSS 支持及 256 MiB profile |
| 管理和诊断 | LuCI/HTTPS、SFTP、iperf3、ethtool、只读核查脚本 |
| 防火墙 | fw3 / iptables |
| 应用迁移 | 首轮不包含现用 HomeProxy、ARM64 sing-box 和私有配置 |

这与之前发生客户端关联后内核 Oops 的 Linux 6.18 NSS 候选属于不同驱动栈。当前没有证据证明故障已修复，也不能把原候选的构建通过记录当成本分支的实机验证。

现有 HomeProxy 使用 fw4/ucode；现用 sing-box 包是 ARM64。本轮先建立可测量的基础转发和无线对照。代理功能需要另行完成 ARM32、fw3 适配或选择经核验的替代应用，并重新验证分流流量与 NSS 的关系。

公开固件遵循上游的首次设置方式，不嵌入管理员密码、Wi-Fi 密码、订阅、SSH 主机私钥或设备备份。无线应在本机单独设置加密后再进行客户端测试。

## 仓库构建

[QSDK workflow](../.github/workflows/qsdk-candidate.yml) 在 `codex/qsdk-nss-candidate` 的相关文件变更时运行，也支持手动触发。运行环境为 Ubuntu 22.04 / Python 3.10，以配合旧版工具链；Windows 本机可运行 Python 输入核验和测试，完整固件使用 Linux CI 编译。

主要阶段：

1. 校验现有公开依赖，运行 Python 测试和 shell 语法检查。
2. 检出固定 QSDK 源码，核对工作区和受审文件摘要，再应用公开构建定制。
3. 检出四个固定 feed，安装后重新写入候选配置，再执行 `make defconfig`，检查选中的 profile、内存配置、NSS、ECM 和应用包未被静默丢弃。旧版 feeds 脚本会自动刷新已有配置，因此配置种子必须在安装完成后重新写入；ccache 同时要求启用 `DEVEL`。
4. 核对并还原原始下载归档及逐文件摘要。补充来源由固定配方管理的诊断包等下载。
5. 编译 host tools、ARM32 工具链、固件、同批软件包、SDK 和独立 ImageBuilder。失败时以串行详细日志重试，不使用 `IGNORE_ERRORS=1`。
6. 保存同批产物，再解析实际 factory UBI、内核 FIT、编译后的设备树和 SquashFS，检查 ECC、频率、内存、ARM32 模块 ABI、无线/NSS 固件与真实开机链接。

核心本地核验命令：

```powershell
python -m unittest discover -s tests -p "test_*.py"
python scripts/qsdk_candidate.py verify-config firmware/qsdk/cr8808.config
```

Linux 源码树准备入口：

```text
python scripts/qsdk_candidate.py prepare --source tmp/qsdk-source --output tmp/qsdk-preparation
python scripts/qsdk_candidate.py feeds --source tmp/qsdk-source
python scripts/qsdk_candidate.py restore-downloads --source tmp/qsdk-source --archive tmp/qsdk-reference/dl.tar
python scripts/qsdk_candidate.py verify-config tmp/qsdk-source/.config
python scripts/qsdk_candidate.py verify-downloads --source tmp/qsdk-source
python scripts/qsdk_candidate.py finish --source tmp/qsdk-source --output tmp/qsdk-artifacts
```

`prepare` 要求源码 HEAD 与锁定提交一致、工作区干净，并拒绝覆盖已有 overlay；输入、准备输出分离。`restore-downloads` 在解包前验证完整归档和清单，仅允许平铺普通文件，拒绝路径穿越、符号链接、重复文件和摘要不符。

ECM 上游 init 脚本的 shebang 有额外空格，不能依赖构建系统自动生成启动链接。本项目策略包明确安装 `S19qca-nss-ecm`；产物检查直接检查镜像里的符号链接和 NSS 模块，而不是只检查 `.config`。

## 构建产物和维护

Actions 附件名为 `cr8808-qsdk-candidate-<本仓库提交>`，保留 30 天。应同时检查 Actions 最终状态和 `build-report.json`；失败任务也保存日志和已有产物，附件存在本身不表示构建验收通过。

- `*-squashfs-nand-factory.ubi`、`*-initramfs-fit-uImage.itb` 和包清单。
- `matching-packages-and-images.tar.zst`：同一构建的目标产物和包目录，包含匹配的 SDK、ImageBuilder、内核模块和包索引。
- `source-lock.json`、下载清单、已解析配置、构建元信息、准备报告、构建报告、源码改动补丁和公开 overlay。
- `SHA256SUMS`、`SHA256SUMS-bin`、实际下载摘要与各阶段日志。只提供构建签名公钥，不归档构建签名私钥。

镜像默认禁用远程 opkg feed，避免旧 QSDK ABI 指向当前通用仓库，出现 404 或装入不匹配模块。补包使用同次 CI 的匹配包集；不要直接批量升级系统包或混入现用 6.6/6.18、ARM64 的模块与应用包。

源码仍以 2024 年的历史基线为基础。来源可追溯解决的是复现与审计问题，不代表已完成后续安全维护或适合长期运行；长期版本还需单独梳理维护补丁和实际使用功能。

## 本仓库首个通过检查的构建

2026-10-31，本仓库提交 [`764a5a5e65a5d4a5787780debd9ef9d8ede9191f`](https://github.com/yingjiedev/cr8808-customize/commit/764a5a5e65a5d4a5787780debd9ef9d8ede9191f) 的 [QSDK 完整构建](https://github.com/yingjiedev/cr8808-customize/actions/runs/41205089925) 和 [Windows / Linux 基线检查](https://github.com/yingjiedev/cr8808-customize/actions/runs/41205089932) 均成功。

[下载本轮完整附件](https://github.com/yingjiedev/cr8808-customize/actions/runs/41205089925/artifacts/13044627252)，其中包含直接可核对的 factory、initramfs、构建报告，以及同批软件包、SDK 和 ImageBuilder。Actions 附件保留至 2026-11-30；维护时应同时保存附件与 [构建核验记录](cr8808-qsdk-build-764a5a5.json)。该记录固定本轮构建提交，后续仅更新文档不会改变已有镜像的来源身份。

| 实际产物检查 | 结果 |
| --- | --- |
| factory | 13,238,272 字节，即 12.625 MiB；低于 32 MiB 候选限制和原有 36 MiB 系统槽 |
| NAND / FIT | ECC4/512；ARM / LZMA，加载和入口地址均为 `0x41208000`，与原发布参考镜像一致 |
| 内存 / 频率 | 256 MiB profile；Q6 保留 48 MiB、NSS 保留 8 MiB；CPU 上限 1.008 GHz |
| 实际 rootfs | ARM32；六个 NSS、ECM 和 ath11k 模块的 ELF 与 Linux 5.4.164 vermagic 一致 |
| NSS / 无线固件 | NSS 固件摘要与已核对的上游基础镜像一致；IPQ5018、QCN6122 无线固件齐全 |
| 开机启动 / 软件源 | 镜像内 NSS、ECM 启动链接齐全；远程 opkg feed 已禁用 |
| 维护产物 | 同批 SDK、独立 ImageBuilder 和软件包已生成，SDK / ImageBuilder 已解包取出并核对摘要 |
| 独立本地复核 | 完整附件摘要与 GitHub 上传记录一致；镜像结构、文件系统、模块、固件和内嵌来源信息均通过检查 |

完整 SHA256、文件大小、CI 和附件标识见构建核验记录。镜像大小与系统槽的差额不能直接当作首启后的 overlay 可用容量，后者还受 UBI 卷分配和坏块保留影响。

本轮只完成构建与静态产物检查，未连接或刷写路由器。Wi-Fi 实机稳定性、持续 500 Mbps NAT、NAS 千兆交换和 HomeProxy 迁移仍需分别验收。

## 待完成的设备验收

- 保持当前可用系统和恢复路径，单独核对候选镜像与实际设备，再安排有线试启。构建流程不包含刷写操作。
- 双频客户端认证、关联、持续传输与重连；检查 Oops、固件崩溃、内存和重启记录。
- 在千兆隔离上游测试网中，用另一台主机作为 WAN 端流量源，电脑位于 LAN 侧，测量真实 NAT 转发；普通 LAN 内 iperf 或在路由器自身发流不能替代这项测试。
- 持续 NAT 不低于 500 Mbps，同时采样 CPU、softirq、内存、丢包、ECM 流和 NSS 计数，确认流量实际被加速。
- NAS 纯 LAN 大文件交换单独验收，目标维持千兆级吞吐。
- 补齐代理应用后，复验国内直连、代理流量、DNS 和 NSS 兼容性，再决定是否作为日常系统。
