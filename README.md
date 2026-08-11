# AviumUI x Waydroid A16

这是 AviumUI `avium-16.2`（Android 16）Waydroid arm64 的可复现配方仓库，不是 Android 源码树。目标是从固定 manifest、固定补丁 series 和记录过的构建环境生成成对的 `system.img`/`vendor.img`，并为 Linux host app 提供按 task 路由的独立 Wayland 窗口，同时保留 AviumUI 默认全屏与原生小窗。

当前仓库仍处于重构和验收阶段。已有实验镜像、构建机 dirty tree 和窗口实验不能代替新的 clean build；本文不宣称部署或三入口真机验收已经完成。

## 唯一入口

所有正式 A16 构建动作都从 [`scripts/avium-a16.sh`](scripts/avium-a16.sh) 进入。命令格式为：

```text
scripts/avium-a16.sh [--root AOSP_ROOT] [--jobs N] [--provenance PATH] preflight|apply|build|verify|all
```

最短路径（在全新的 AOSP checkout 中）是：

```bash
repo init -u https://github.com/AviumUI/android_manifests \
  -b 981823afd5a1c3fcf740cd3b4eeeb61331ca8304 \
  --manifest-upstream-branch avium-16.2 --git-lfs
mkdir -p .repo/local_manifests
cp /path/to/aviumui-waydroid/manifests/waydroid.lock.xml .repo/local_manifests/waydroid.xml
repo sync
/path/to/aviumui-waydroid/scripts/avium-a16.sh --root "$PWD" all
```

`all` 依次执行输入检查、A16 release series、A16 window series、严格 final-tree 检查、`lunch`、成对镜像构建和 provenance 验证。需要分步操作时使用 `preflight`、`apply`、`build`、`verify`；正式 `build` 要求 release 与 window 两组完成 tree 同时匹配。任何 patch digest、base tree、dirty-tree 或 expected-tree 错误都会在进入编译前停止。构建命令固定为：

```bash
lunch lineage_waydroid_arm64_only bp4a userdebug
m -j8 systemimage vendorimage
```

产物在 `out/target/product/waydroid_arm64_only/system.img` 和 `vendor.img`；默认 provenance 在 `out/avium-a16/provenance.json`，包含 manifest、local manifest、release/window series、逐项 window patch SHA-256、源码 tree、构建时间、命令和两张镜像的 SHA-256。

## 文档入口

- [`docs/SOURCES.md`](docs/SOURCES.md)：AviumUI 来源、固定 manifest 和输入锁。
- [`docs/PORTING-A16.md`](docs/PORTING-A16.md)：Waydroid A16 补丁分类、手动移植和跳过条件。
- [`docs/BUILD-A16.md`](docs/BUILD-A16.md)：构建机、依赖、磁盘门、构建和产物记录。
- [`docs/FIX-LEDGER.md`](docs/FIX-LEDGER.md)：正式源码修复、环境修复、临时止血和证伪实验的账本。
- [`docs/WINDOW-ARCHITECTURE.md`](docs/WINDOW-ARCHITECTURE.md)：三种启动来源的 per-task 窗口架构和保留/删除边界。
- [`docs/ACCEPTANCE.md`](docs/ACCEPTANCE.md)：自动检查、镜像验收和真机回归门。
- [`docs/ARCHIVE.md`](docs/ARCHIVE.md)：历史脚本、证据和旧产物的索引与排除理由。

旧研究仍可从 [`docs/COEXIST-BASELINE.md`](docs/COEXIST-BASELINE.md)、[`docs/FIXES.md`](docs/FIXES.md) 和 [`docs/WINDOWING.md`](docs/WINDOWING.md) 查阅，但它们不是新的正式入口；冲突时以源码、锁文件、构建日志和运行证据为准。
