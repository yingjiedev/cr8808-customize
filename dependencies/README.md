# 依赖与当前设备基线

本目录的 `lock.json` 是版本、文件大小、SHA256、源码提交、内核 ABI 与补丁输入/输出的唯一清单。维护流程见[依赖维护手册](../doc/cr8808-dependency-maintenance.md)。

- `../vendor/packages/`：本次安装的全部增量 IPK、原始 tiny 内核输入包及 r2 回滚包。
- `../vendor/firmware/`：已刷入固件的原始公开 factory 镜像；不是设备导出或备份。
- `../vendor/sources/`：固件及其四个 feeds、sing-box、ucode、SquashFS 工具的固定源码快照。
- `../vendor/tools/`：本次电脑端检测与压缩使用的官方工具发行包。
- `../upstream/homeproxy/`：与安装版本对应的完整、可编辑 HomeProxy 源码。
- `../upstream/recipes/`：sing-box 与 ucode 包配方，保留原始许可头。
- `baseline/`：发布者的固件包清单、构建参数、feeds 提交及校验表。
- `licenses/`：第三方许可；源码文件内的版权与许可声明同样有效。

SDK、ImageBuilder、工具链及补充恢复镜像体积较大，清单中标记为 `download`，不计为已入库文件。通过显式 `fetch ID` 下载并校验，保存到忽略的 `tmp/dependencies/`。普通验证与应用包构建只读仓库文件，完全不访问这些外部文件或软件源。

```powershell
python scripts/manage-dependencies.py verify
python scripts/manage-dependencies.py build --output tmp/builds/baseline-1
```

归档使当前版本可取回、可核对；源码重新编译与安全更新仍需维护和验收。Go 间接依赖由 sing-box 源码内的 `go.mod` / `go.sum` 固定，未把整个 Go 模块缓存纳入 Git。固件的外部上游源码下载由固定配方管理，未声称已完成全离线固件重编译。
