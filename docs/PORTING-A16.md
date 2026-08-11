# Waydroid A16 移植

## 补丁分类

Waydroid `dev/lineage-23.2` 的原始 170 个补丁按源码可验证结果分为：

| 类别 | 数量 | 处理 |
| --- | ---: | --- |
| direct | 164 | 按原补丁应用 |
| manual | 4 | 固定在本仓库的手动移植补丁 |
| justified skip | 2 | 只有 predicate 成立时跳过 |

上游清单见 [`patches/a16/upstream-series.json`](../patches/a16/upstream-series.json)。正式 release series 还包含 11 个 A16/AviumUI 构建修复，共 179 个实际 patch，另有相同的 2 个 skip；见 [`patches/a16/release-series.json`](../patches/a16/release-series.json)。其中 release series 按 41 个 project 组织，直接和手动补丁的源码归属可从 JSON 逐项审阅。

## 手动移植

这四项不是“补丁失败后继续编译”的隐式修改，而是正式 series 的明确文件：

- `build/soong/0002-fix-building-on-a16.patch`
- `system/core/0009-override-ro-vndk-lite.patch`
- `frameworks/base/0012-idle-inhibit.patch`
- `frameworks/base/0017-waydroid-framework.patch`

## 有依据的跳过

- `device/google/atv/0001-Lift-maxUiWidth-restiction-on-ATV.patch`：local manifest 移除了 `device/google/atv`，predicate 为 `missing_project:device/google/atv`。
- `lineage-sdk/0008-trust-Suppress-SELinux-warning.patch`：AviumUI 的 Trust cleanup 已移除 `TrustInterfaceService`，predicate 检查其实现文件不再包含 `postNotificationForFeatureInternal`。

应用器 [`scripts/apply-a16-upstream-patches.py`](../scripts/apply-a16-upstream-patches.py) 会先在临时 worktree 检查整个 series，再在成功后更新真实 checkout；它拒绝 dirty project、错误 base HEAD、错误完成 tree 和不成立的 skip predicate。`--check-only` 可在不写入源码的情况下检查可重放性。

## A16 修复附加项

release series 中的 11 个本地修复覆盖 Mesa 的系统 Python/Meson、minigbm 的 `unistd.h`、framework AppOp/SecureLock、HWC2 adapter ownership、arm64/cuttlefish key、WayDroidService 资源、平台测试的 Cuttlefish 依赖、容器内只读 sysfs，以及 AviumUI 多余 generated kernel headers。每一项的症状、根因和证据归类见 [`docs/FIX-LEDGER.md`](FIX-LEDGER.md)。

窗口共存不混入这 179 个 A16 release patch；它由独立的 [`patches/windowing/a16/series.json`](../patches/windowing/a16/series.json) 在 release 完成 tree 之后重放。这样即使窗口工作尚未通过真机门，A16 基线的来源、补丁分类和构建修复仍可单独审计。窗口 series 当前覆盖 frameworks/base、hardware/waydroid、lineage-sdk 与 device/waydroid/waydroid；不引用会全局接管 freeform display 的旧 desktop-first overlay。

## 机器检查

```bash
python3 scripts/test-a16-series.py
python3 scripts/test-a16-series.py --aosp-root /path/to/clean/aosp
```

第二条命令需要完整 checkout，并会做逐 project 的临时 worktree replay；当前没有把旧构建树的 dirty 状态当作通过条件。
