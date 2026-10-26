# CR880x 历史 WebUBoot 候选包

**状态：尚未通过本机启动验证，不是可直接安装的已验证版本。**

本目录保存用户提供的三份原始候选二进制、修正说明、校验值和来源记录。只修正操作说明，**没有修改或重新编译 U-Boot 二进制**。它们与 [Lenoud 资源仓库固定版本](https://github.com/Lenoud/cr8809-miwifi-openwrt/tree/52e90d5b08f47f3e5d7519795e0b4d6cdd1cc3a8/CR880X%E5%90%88%E5%B9%B6%E5%88%86%E5%8C%BA%E5%B9%B6%E5%88%B7%E5%B8%A6web%E7%9A%84uboot)对应文件逐字节一致。

## 本次修正

- 备引导目标名修正为 `0:APPSBL_1`；`APPSBL1.bin` 是文件名。
- 将 Linux SSH 与 U-Boot 串口的执行环境分开说明。
- 删除把“刷入相同 MIBIB”当作必需合并分区步骤的说法。本机无需为匹配此文件重写 MIBIB。
- 不再把主、备引导当作等价救援副本，也不沿用未验证的逐步断电流程。
- 明确串口、写入边界、启动兼容与读回校验均需验证；仅文件哈希一致不足以决定重启。

完整内容见[修正说明.txt](修正说明.txt)、[专项核查](../../../doc/cr8808-local-webuboot-review.md)及[测试状态](../../../doc/cr8808-webuboot-test-status.md)。

## 先做本地检查

在项目根目录的 PowerShell 执行，需要 Python 3.8 或更新版本：

```powershell
python .\scripts\check-webuboot-package.py
```

本机已有原厂备份时可同时复核：

```powershell
python .\scripts\check-webuboot-package.py --backups .\tmp\xmir-patcher\backups
```

典型返回：

```text
PACKAGE_INTEGRITY_OK: 3 pinned files
MIBIB_TABLE_OK: 22 partitions; rootfs and rootfs_1 are 36 MiB each
ELF_STRUCTURE_OK: ARM32; entry 0x4a920000
LOCAL_BACKUPS_OK: 24 files; 22 physical partitions, 127 MiB
CANDIDATE_MIBIB_EQUALS_LOCAL_BACKUP: yes
DEVICE_COMPATIBILITY: NOT_VERIFIED
FLASH_ALLOWED: NO
REBOOT_ALLOWED: NO
```

前五行通过表示本地文件和已有备份检查通过，**不是路由器适配或刷写许可**。脚本没有联网、串口、Flash 写入、修改环境或重启功能；失败会以非零状态退出。

文件完整性由 `SHA256SUMS`、`manifest.json` 和脚本内固定校验值共同记录。校验值不等于原作者签名。
