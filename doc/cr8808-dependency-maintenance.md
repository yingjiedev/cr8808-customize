# CR8808 依赖归档与持续维护

2026-10-27，以当前已验证的主路由配置为第一份维护基线。这里维护应用、补丁、构建输入和固件来源；本次整理不更换正在工作的路由器固件。

## 1. 维护范围

当前固件来自已归档的 [kmiit/Redmi_AX3000_immortalwrt](https://github.com/kmiit/Redmi_AX3000_immortalwrt)，固定源码为 `9a11bb83d22efd5879439427cd222b957f6f7019`。这不表示 [ImmortalWrt](https://github.com/immortalwrt/immortalwrt) 或 [HomeProxy](https://github.com/immortalwrt/homeproxy) 主项目已停止维护。

| 层次 | 当前基线 | 在本仓库怎样维护 |
| --- | --- | --- |
| 固件与基础系统 | 24.10-SNAPSHOT r0-9a11bb8 | 原始 factory 镜像、完整基础包版本清单、源码与四个固定 feeds 快照 |
| 内核与模块 | 6.6.137；ABI `6.6.137~20a052f3c3e98b3a9ba1a095f81e2725-r1` | 六个本次新增模块归档；按完整 ABI 验证，不跨固件替换 |
| HomeProxy 与中文包 | 26.236.50592~9b8ee64 | 原始 IPK、完整源码、固定输入补丁、行为测试 |
| sing-box | tiny 1.12.25；本地 squashfs 1.12.25-r3 | 原始 IPK、源码、配方、64 KiB 镜像与挂载服务；r2 可回滚 |
| ucode digest | 2025.07.18~3f64c808-r1 | IPK、对应源码与固件内配方；其余 ucode 运行时随原始固件保存 |
| 自定义功能 | 内存参数、功能缓存、WAN 启停、逐个及一键排队测速、日志下载权限 | `scripts/` 作为维护入口，构建时生成完整覆盖文件 |
| 电脑辅助工具 | sing-box Windows 1.12.25、squashfs-tools-ng 1.3.2 | 官方发行包入库，版本与哈希固定 |
| SDK / ImageBuilder / 交叉工具链 | 当前固件同一 Release | 在本仓库 Release 镜像，锁定大小与 SHA256，显式下载到本机缓存 |

基础系统里的 libc、BusyBox、dnsmasq、firewall4、rpcd、LuCI、无线驱动等由完整原始固件和 `dependencies/baseline/firmware.manifest` 保存，不把后来软件源里的同名包视作替代品。`verify` 会检查增量 IPK 的每条包依赖能由归档包或该基础清单满足，并核对内核 ABI。

首次归档共有 37 个受校验文件，约 102.3 MiB，另有 3 个源码目录；原固件包含 220 个基础包，当前运行增量包为 10 个。Windows 本地离线构建已通过，重新打包的 r3 IPK SHA256 为 `4e8bb53e19fe7c17da67828907edcd6a624b7797b7185dff3f492d8439a03af6`，七个定制输出均与已验证版本吻合。GitHub Actions 已配置跨平台检查，运行结果以仓库实际记录为准。

**可以持续维护应用层；维护整套固件还需要另一个验收过程。** 保存旧文件不会修复内核和驱动漏洞。切换基础固件时，需要重建内核模块、核对 CR8808 设备树与原厂分区路线，并重新验证有线、无线、NAT、启动恢复和内存。不能通过一次 `opkg upgrade` 完成这件事。

## 2. 仓库布局与校验

`dependencies/lock.json` 记录所有受管文件的 SHA256、字节数、用途、来源、许可证和包依赖。`vendor/` 保存公开二进制与压缩源码，`upstream/` 保存可编辑的应用源码与配方，`scripts/` 保存我们的修改。

在项目根目录执行：

```powershell
python scripts/manage-dependencies.py list
python scripts/manage-dependencies.py verify
python -m unittest discover -s tests -p "test_*.py"
node --test tests/homeproxy-node-ui.test.cjs
```

Python 工具只使用标准库，构建基线使用 Python 3.13；Node 测试使用内置测试框架，无需安装 npm 包。校验不执行归档的二进制，不连接路由器，不读取本机配置备份，也不依赖软件源在线。版本、文件或哈希不符时直接失败。

克隆时保留二进制和上游文件的原始字节；`.gitattributes` 已明确相应规则。不能通过转换换行来“修复”校验失败。

## 3. 离线构建当前应用基线

```powershell
python scripts/manage-dependencies.py build --output tmp/builds/baseline-1
```

输出目录必须不存在。构建包含以下步骤：

1. 核对所有入库依赖、源码目录与包依赖。
2. 从原始 tiny IPK 取出相同 ELF，从 r3 IPK 取出已验证镜像，核对 ELF 与镜像哈希及 64 KiB 块，然后重打 r3 包并核对包哈希。
3. 从原始 HomeProxy IPK 取出真正交付的 init、生成器、RPC 与页面，依次应用定制补丁。默认要求输出哈希与当前已验收基线一致。
4. 生成 `overlay/`、公开依赖包与源码 ZIP、`SHA256SUMS` 和 `build-report.json`。

ZIP 名称为 `cr8808-homeproxy-baseline.zip`，含十个当前运行增量包、八个覆盖文件、源码与许可（增加已实机验证的 HomeProxy 日志下载 ACL）。它不含个人配置，不能代替本机私有恢复备份；也不是可直接刷写的固件。Windows 解压可能不保留执行权限，部署时必须设置 init/hotplug 为 `0755`、ucode/JS/ACL JSON 为 `0644`。

这里验证的是现有应用包的离线重打和补丁重建。未声称新编译的 ELF 与官方 ELF 相同，也未声称重新生成 SquashFS 镜像或整套固件可以逐字节一致。镜像重建使用归档的 gensquashfs、相同 ELF、XZ 和 65536 字节块，按[脚本说明](../scripts/README.md)操作并重新登记哈希。

## 4. 迭代方式

定制功能优先修改 `scripts/homeproxy-low-memory/` 或相应补丁脚本，运行测试后生成候选包：

```powershell
python scripts/manage-dependencies.py build --candidate --output tmp/builds/candidate-1
```

候选模式生成 `cr8808-homeproxy-candidate.zip`，仍校验原始依赖与输入，但允许定制输出变化，单独记录输出哈希，**不会修改已验收依赖锁**。若修改压缩挂载服务，也会记录新打包哈希；正式发布需用原有打包脚本增加本地包 revision，再登记新包与依赖锁，不能以新内容冒充旧 r3。

在同一固件测试候选时，先保存私有配置和旧覆盖文件，再用 `sh check-device.sh` 做只读兼容检查，检查空闲 flash/RAM，并在路由器对 shell/ucode 做语法检查。一次只部署相关改动；RPC 改动需重启 rpcd，生成器或核心改动需重启 HomeProxy，页面改动刷新浏览器即可。安装新原包后再覆盖补丁，避免原包把补丁覆盖。配置按[资源优化手册](cr8808-low-memory-homeproxy.md)应用，构建包不会自动改写节点、订阅或 Wi-Fi。

验收至少覆盖页面打开、订阅保存、国内直连/名单网站代理、单节点测试、全部队列、停止/页面退出、低内存保护，并观察 OOM、CPU、MemAvailable 与常驻进程数。当前队列保持并发 1、间隔 1 秒；原 42 节点实测最低可用内存约 10.7 MiB，不能只凭空闲时内存提高并发。确认后将结果写入手册，再更新 `lock.json` 中已验收的输出哈希与版本。

升级 HomeProxy 或 sing-box 时，还要更新源码快照、原始 IPK、许可、构建输入和回滚说明。现有补丁含版本与哈希保护；不得删除保护后强套新版本。sing-box 功能缓存固定了 ELF 哈希、长度与功能，新 ELF 必须重新核对这些数据。源码快照的 `go.mod` / `go.sum` 保存 Go 模块版本及校验，模块下载缓存未全部入库。

## 5. 固件源码和大文件

当前固件完整源码和发布时四个 feeds 已保留在 `vendor/sources/`；`config.buildinfo`、`feeds.buildinfo` 是发布者提供的构建记录。HomeProxy 后装版本取自另一个、更新的 LuCI 提交，单独放在 `upstream/homeproxy/`，不要将两者混为同一源码状态。

可按需获取固定大文件：

```powershell
python scripts/manage-dependencies.py fetch firmware-sdk
python scripts/manage-dependencies.py fetch firmware-imagebuilder
python scripts/manage-dependencies.py fetch firmware-toolchain
```

这些大文件随 [v0.1.0](https://github.com/yingjiedev/cr8808-customize/releases/tag/v0.1.0) 发布为独立附件。依赖锁优先指向本仓库 Release，保留上游备用 URL；二进制内容不变，仍使用原发布者的哈希。下载后核对锁定大小和 SHA256，成功才更名为最终文件。默认应用构建不会自动下载或运行它们，下载后可用 `python scripts/manage-dependencies.py verify --downloads` 核对全部缓存。

Release 还包含应用基线 ZIP、原始 factory 镜像、公开仓库完整快照、构建报告、依赖锁、逐附件 SHA256 和许可说明。发版从已提交的 Git 快照取文件，只复制清单指定的大文件，不扫描其他本机缓存。SDK、ImageBuilder 与工具链用于 Linux x86_64 构建环境，不是在路由器上运行的包。

重编固件需在 Linux/WSL 的 Linux 文件系统内准备环境，展开固定固件与 feeds，依据固定配方补齐源码下载缓存，再编译与设备验收。SDK 已作为 Release 附件归档，但不进入 Git；所有 Linux 上游源码包、Go 模块缓存仍未完整镜像，也未完成一次新固件编译。SDK 用于交叉编译用户态软件，不代表能不经核对地生成相同 ABI 的内核模块。

## 6. 发布流程与许可

仓库原创代码、脚本及文档采用 GPL-2.0-or-later；HomeProxy、sing-box、ucode、固件与工具链等第三方组件保留原有许可，详见根目录 `LICENSE` 与 `LICENSING.md`。

发版配置为 `dependencies/release.json`，说明为 `doc/releases/版本号.md`。维护者先完成改动和验收，更新版本配置并提交，然后推送匹配的版本标签，例如：

```powershell
git tag -a v0.1.0 -m "CR8808 maintenance baseline v0.1.0"
git push origin main v0.1.0
```

标签仅创建一次；已发布的版本不得覆盖或移动。Release workflow 会运行测试、从上游下载五个锁定大文件并校验、离线构建应用包，生成公开快照及校验清单。全部准备好后先创建草稿，逐个上传，要求 GitHub 返回的附件大小和 SHA256 与本机清单一致，才公开发布。只给发布任务 `contents: write`，令牌留在 Actions 中。

若上传中断，可在 Actions 的 `Publish verified Release` 中对同一标签重新运行。若修复的是发布工具，在默认分支的工作流中手工选择原标签；源码与附件仍从原标签构建，发布器使用本次工作流版本并独立测试，不移动标签。草稿通过已认证的 Release 列表和固定 ID 查找，不依赖仅按标签查询的公开接口。

脚本复用内容完全相同的草稿附件；遇到同名不同内容会停止，不覆盖。已公开版本仅允许完整一致时直接返回成功。新内容应使用新版本。

手工准备和发布入口如下，发布需要 GitHub CLI 及该仓库写权限：

```powershell
python scripts/manage-release.py prepare --tag v0.1.0 --output tmp/release --download
python scripts/manage-release.py publish --tag v0.1.0 --assets tmp/release/assets
```

首次准备使用依赖锁的 `upstream_urls`，避免依赖尚未发布的自身镜像。正常用户下载继续使用 `fetch ID`，优先本仓库镜像。

## 7. CI、回滚与凭据

GitHub Actions 在 Linux 和 Windows 上校验依赖、运行 Python/前端测试、离线构建应用包，再上传构建产物供审阅。它不接触家庭路由器，不自动升级依赖、不部署候选，也不把未经实机验收的更新标为稳定。Actions 的外部步骤按提交 SHA 固定。

回滚依旧使用本机保存的配置备份；公开仓库额外保存 r2 核心、原始 HomeProxy IPK 和构建源码。单纯回退应用版本，不等于回退基础固件或个人配置。原始 factory 镜像仅用于相应的完整恢复路线，不能把它当成应用更新包执行。

禁止把订阅 token、代理节点配置、Wi-Fi 密码、`node-test.secret`、shadow、设备分区和私有恢复 ZIP 放入公开归档。构建器从显式公开清单取文件，不扫描或打包 `tmp/`。相关私有资料继续留在原有本机备份位置。
