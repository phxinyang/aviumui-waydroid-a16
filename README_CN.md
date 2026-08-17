# AviumUI × Waydroid A16

[English](README.md)

基于 AviumUI（LineageOS 23.2 / Android 16）的 Waydroid arm64 构建配方仓库。
仓库不包含 Android 源码，只包含锁定 manifest、补丁系列和构建入口，配合
AviumUI 官方 manifest 从零构建成对的 `system.img` / `vendor.img`。

## 结构

```text
manifests/   waydroid.lock.xml（锁定的 local manifest，固定全部项目 revision）
patches/
  a16/       A16 Waydroid 移植补丁（upstream 官方移植 / fixes 本地修复 / manual 手工调整）
  windowing/ 多窗口路线补丁（per-task Wayland 窗口）
scripts/     avium-a16.sh 构建入口 + 补丁应用/校验脚本 + 自测
docker/      Ubuntu 24.04 构建环境（固定基础镜像）
docs/        来源、移植、窗口架构、修复账本
```

## 构建

在 Docker 环境（或等价 Ubuntu 24.04 环境）中：

```bash
repo init -u https://github.com/AviumUI/android_manifests \
  -b 981823afd5a1c3fcf740cd3b4eeeb61331ca8304 \
  --manifest-upstream-branch avium-16.2 --git-lfs
mkdir -p .repo/local_manifests
cp manifests/waydroid.lock.xml .repo/local_manifests/waydroid.xml
repo sync
scripts/avium-a16.sh --root "$PWD" all
```

产物在 `out/target/product/waydroid_arm64_only/system.img` 和 `vendor.img`，
provenance 记录在 `out/avium-a16/provenance.json`。

## 源码引入

本项目不包含 Android 源码。构建时通过 repo 从上游拉取：

- **AviumUI**（`github.com/AviumUI/android_manifests`，分支 `avium-16.2`）：
  LineageOS 23.2 / Android 16 基础源码，约 1085 个项目。
- **Waydroid 组件**（`waydroid.lock.xml`，作为 local manifest 叠加）：
  33 个项目，来自 waydroid / WayDroid-ATV / intel / android-generic 等组织，
  覆盖设备树、HAL、媒体栈、GApps 等。

锁定关系：`manifests/a16-recipe-lock.json` 固定 AviumUI manifest HEAD、
local manifest SHA-256、全部项目 revision 和 LFS 文件哈希；补丁系列
（`patches/`）在锁定源码上应用，最终 tree 由 series 校验。

## 文档

- [docs/SOURCES.md](docs/SOURCES.md)：来源与输入锁
- [docs/PORTING-A16.md](docs/PORTING-A16.md)：A16 移植说明
- [docs/WINDOW-ARCHITECTURE.md](docs/WINDOW-ARCHITECTURE.md)：多窗口架构
- [docs/FIX-LEDGER.md](docs/FIX-LEDGER.md)：修复账本

## 许可

本仓库以 Apache-2.0 发布（见 [LICENSE](LICENSE)）；补丁保留上游项目各自
的许可，Waydroid GPL 组件的补丁遵循 GPL-3.0，详见 [NOTICE](NOTICE)。
