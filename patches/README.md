# patches/ —— 树内源码改动的导出（部分待补 ⚠）

本目录应存放 AOSP 树内**裸改动**（非 waydroid 补丁）的 patch 导出。当前**尚未导出**，以下改动仍只存在于 `/build` 的 AOSP 树里，`repo sync` 会抹掉。

## 缺口清单（按优先级）

### 缺口 1：apexd 修复（最高优先级）
- 文件：`system/apex/apexd/apexd_loop.cpp`，3 处改动（fsopen fallback + read_ahead 两处 return 注释掉）
- 依据：redroid-doc issue #925 + dragon-waydroid 补丁
- 详见 [docs/FIXES.md](FIXES.md) B1
- **为什么高危**：整个项目最难定位的修复，唯一副本在树里，`repo sync` 即丢（历史上 170 补丁已被抹过一次）
- **导出方式**：
  ```bash
  cd /build/system/apex
  git diff > patches/apexd_loop_fix.patch
  ```

### 缺口 2：SecureLockDeviceRepository try-catch
- 文件：`frameworks/base/packages/SystemUI/src/com/android/systemui/securelockdevice/data/repository/SecureLockDeviceRepository.kt`
- register/unregister 各包 `catch (_: SecurityException)`
- 详见 [docs/FIXES.md](FIXES.md) C3
- **额外断链**：`scripts/resume-build.sh` 里 `if ! grep -q 'catch (_: SecurityException)' ...` 分支调用 `/build/patch_secure_lock.py`，**该文件在构建机上不存在**。当前能跑是因为条件为假直接跳过；树一旦重置，此修复无法重建。
- **修法**（二选一）：
  - 导出成 patch 放进本目录，改 resume-build.sh 用 `git apply`
  - 或写一个幂等的 `patch_secure_lock.py`（sed/正则注入 try-catch），重建脚本链

### 缺口 3（半满）：RANGING / AppOpService
- `core/res/AndroidManifest.xml` 的 RANGING featureFlag 移除：**已由 resume-build.sh 的 sed 幂等处理**（非树内裸改，重建无忧）
- `AppOpService.kt` 的 `checkNotNull` → `?: continue`：已由 `scripts/patch_appop.py` 幂等处理 ✓

### 缺口 4：init.rc placeholder
- waydroid 补丁会把 rootdir/init.rc 改成 placeholder（`write` 而非 `exec /system/bin/bootstrap/linkerconfig`）。属于 170 补丁之一，随 patch-and-build.sh 重建 ✓

## 验收标准

树内裸改导出齐全后，本目录应满足：**在干净的 AOSP 树 + 全部 waydroid 补丁之后，`resume-build.sh` 不依赖任何 `/build/*.py` 之外的文件，能完整复现当前 system.img**。届时删除"⚠ 待补"标记。
