# patches/ —— 树内源码改动的导出（部分待补 ⚠）

本目录应存放 AOSP 树内**裸改动**（非 waydroid 补丁）的 patch 导出。当前**尚未导出**，以下改动仍只存在于 `/build` 的 AOSP 树里，`repo sync` 会抹掉。

## 缺口清单（按优先级）

### 缺口 1：apexd 树内提交（配方已补，分仓提交待完成）
- 文件：`system/apex/apexd/apexd_loop.cpp`，3 处改动（fsopen fallback + read_ahead 两处 return 注释掉）
- 依据：redroid-doc issue #925 + dragon-waydroid 补丁
- 详见 [docs/FIXES.md](FIXES.md) B1
- `scripts/patch_apexd_container_sysfs.py` 已能从 upstream 或旧注释式现场生成明确的 best-effort 失败路径，并有双遍幂等测试。
- 仍需在 `system/apex` 独立提交并完成窄构建；在此之前 `repo sync` 仍会丢掉构建树提交。
- **导出方式**：
  ```bash
  cd /build/system/apex
  git diff > patches/apexd_loop_fix.patch
  ```

### 缺口 2：SecureLockDeviceRepository try-catch（重放脚本已存在）
- 文件：`frameworks/base/packages/SystemUI/src/com/android/systemui/securelockdevice/data/repository/SecureLockDeviceRepository.kt`
- register/unregister 各包 `catch (_: SecurityException)`
- 详见 [docs/FIXES.md](FIXES.md) C3
- `scripts/patch_secure_lock.py` 已在主配方仓，旧/new block 均有硬门禁；先前“文件不存在”结论已撤销。
- 仍需确认 `frameworks/base` checkpoint 中该改动的最终提交边界，并在干净树重放一次。

### 缺口 3（半满）：RANGING / AppOpService
- `core/res/AndroidManifest.xml` 的 RANGING featureFlag 移除：**已由 resume-build.sh 的 sed 幂等处理**（非树内裸改，重建无忧）
- `AppOpService.kt` 的 `checkNotNull` → `?: continue`：已由 `scripts/patch_appop.py` 幂等处理 ✓

### 缺口 4：init.rc placeholder
- waydroid 补丁会把 rootdir/init.rc 改成 placeholder（`write` 而非 `exec /system/bin/bootstrap/linkerconfig`）。属于 170 补丁之一，随 patch-and-build.sh 重建 ✓

## 验收标准

树内裸改导出齐全后，本目录应满足：**在干净的 AOSP 树 + 全部 waydroid 补丁之后，`resume-build.sh` 不依赖任何 `/build/*.py` 之外的文件，能完整复现当前 system.img**。届时删除"⚠ 待补"标记。
