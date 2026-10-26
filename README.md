# cr8808-customize

CR8808 定制项目。

## 文档

- [Windows 新手完整教程：工具下载、固件下载、命令、典型返回与判断](doc/cr8808-beginner-guide.md)
- [网页恢复 U-Boot 调研：候选项目、文件校验与本机支持路线](doc/cr8808-web-uboot-research.md)
- [本地「02-不死引导-WebUBoot」文件包是否支持本机](doc/cr8808-local-webuboot-review.md)
- [CR8808 刷机实操记录（已刷入并完成重启验证，附命令与实际返回）](doc/cr8808-openwrt-hands-on.md)
- [CR8808 刷入 OpenWrt 调研与操作路线](doc/cr8808-openwrt-flashing-research.md)

调研中间资料、下载文件和设备备份统一放在 `tmp/`，该目录已加入 Git 忽略配置。

本机已安装 ImmortalWrt 24.10-SNAPSHOT，并通过管理员登录和额外重启验证。新手教程只覆盖文中已核对的原厂 CR8808/xpa/ap-mp02.1 双槽位路线；其他硬件或改过引导/分区的机器需要独立核查。

`scripts/prepare-cr8808-flash.ps1` 只检查本地备份并生成设备专用脚本；生成脚本默认只检查，实际写入需要显式传入 `--flash`。当前已刷好的设备无需重复刷写。
