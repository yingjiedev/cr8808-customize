# cr8808-customize

CR8808 定制项目。

## 文档

- [主路由、双频 Wi-Fi 与订阅配置手册（已联网，含页面超时修复）](doc/cr8808-main-router-configuration-manual.md)
- [主路由、Clash/通用订阅与分流配置调研（含本机容量限制）](doc/cr8808-subscription-main-router-research.md)
- [Windows 新手完整教程：工具下载、固件下载、命令、典型返回与判断](doc/cr8808-beginner-guide.md)
- [网页恢复 U-Boot 调研：候选项目、文件校验与本机支持路线](doc/cr8808-web-uboot-research.md)
- [本地「02-不死引导-WebUBoot」文件包是否支持本机](doc/cr8808-local-webuboot-review.md)
- [WebUBoot 修正包与测试状态（尚未执行引导写入）](doc/cr8808-webuboot-test-status.md)
- [CR8808 刷机实操记录（已刷入并完成重启验证，附命令与实际返回）](doc/cr8808-openwrt-hands-on.md)
- [CR8808 刷入 OpenWrt 调研与操作路线](doc/cr8808-openwrt-flashing-research.md)

调研中间资料、下载文件和设备备份统一放在 `tmp/`，该目录已加入 Git 忽略配置。

用户授权整理的历史候选引导包另存于 [firmware/webuboot](firmware/webuboot/cr880x-20221214/README.md)，明确标记为待验证；只修正说明，未修改二进制。设备备份和身份数据不纳入该目录。

本机已安装 ImmortalWrt 24.10-SNAPSHOT，并通过管理员登录和额外重启验证。新手教程只覆盖文中已核对的原厂 CR8808/xpa/ap-mp02.1 双槽位路线；其他硬件或改过引导/分区的机器需要独立核查。

2026-10-27 已在现有系统完成 DHCP 主路由、双频加密 Wi-Fi 和 HomeProxy/sing-box 配置，采用压缩只读应用镜像容纳代理内核。主路由接线已修正，WAN DHCP、电脑基本外网访问和 HomeProxy 页面加载接口已验证；页面功能查询已适配，避免额外启动 sing-box 版本查询进程。具体设置、验收范围、接线排障、操作和恢复方法见配置手册。

`scripts/prepare-cr8808-flash.ps1` 只检查本地备份并生成设备专用脚本；生成脚本默认只检查，实际写入需要显式传入 `--flash`。当前已刷好的设备无需重复刷写。
