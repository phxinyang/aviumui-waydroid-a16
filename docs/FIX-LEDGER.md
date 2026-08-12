# 修复账本

本账本把“可以进入正式 recipe 的源码修复”和“只能帮助一次构建或运行诊断的措施”分开。正式条目必须在 [`patches/a16/release-series.json`](../patches/a16/release-series.json) 或固定输入中可重放；当前没有 clean build 或真机结果的条目不能写成已验收。

## 正式源码修复

| 症状/根因 | 正式修复 | 状态 |
| --- | --- | --- |
| A16 的 RANGING 权限 flag 与无条件 AppOp 不一致，system_server 启动崩溃 | frameworks/base 的 permission/AppOp 一致性补丁 | 已纳入 release series，需 clean build/runtime 复验 |
| `MANAGE_SECURE_LOCK_DEVICE` 被 flag 门控，SystemUI 反复崩溃 | framework SecureLock permission guard 补丁 | 已纳入 release series，需 clean build/runtime 复验 |
| A16 HWC2 adapter buffer ownership 不明确 | hardware/interfaces ownership 补丁 | 已纳入 release series |
| arm64-only camera provider 与 Cuttlefish key 路径不适配 | hardware/interfaces multilib/key 构建修复 | 已纳入 release series |
| WayDroidService 引用 AviumUI 缺失 Trust 资源 | lineage-sdk 恢复资源和 symbols | 已纳入 release series |
| 容器只读 `/sys` 使 apexd 的 sysfs 调优失败 | system/apex best-effort sysfs 修复 | 已纳入 release series |
| `libavium_utils` 依赖不存在的 generated kernel headers | vendor/avium 删除无用依赖 | 已纳入 release series |
| platform_testing 仍引用被移除的 Cuttlefish 模块 | 删除过时依赖 | 已纳入 release series |
| Linux launch、Avium full UI 与 MiFreeform 被全局 desktop 策略混合 | system-UID launch cookie、Task/TaskInfo per-task route、WM Shell route 发布、HWC route map | 已纳入 window series；[`a16-window-locked-replay-20260811-r2`](../evidence/a16-window-locked-replay-20260811-r2/) 已从四个固定 base tree 验证重放，仍需同镜像真机复验 |
| Avium A16 的 Pop-Up View、硬件键和旋转 API 已变化，但 WmTests 仍调用旧字段/签名 | 测试按当前 `Action`、`endTask`、`inPortPopUpView` 和 `getNaturalRotation()` 语义对齐，并新增 system UID/cookie 双条件鉴权覆盖 | 已作为独立 test-only patch 纳入 window series；完整 WmTests APK 与三个过滤配置已编译，尚未在设备端运行 instrumentation |
| external task 与 full UI 不能同时稳定存在 | HWC hybrid carrier、独立 full-UI latch、按 task route 管理 `xdg_toplevel` | 已纳入 window series；需真机生命周期复验 |
| 快速拖动旧帧与多-layer 重复标题栏 | live task 优先于 snapshot、primary-child ownership、每帧退休未使用 subsurface | 已纳入 window series；仍是明确真机回归门 |
| ARM64 Waydroid 上 minigbm_dmabuf IAllocator 无法初始化并抢占 `@4.0::IAllocator/default` | device/waydroid 的 ARM64 产品包选择：排除 dmabuf allocator 服务，改由 minigbm_gbm_mesa 提供服务，保留 mapper/gralloc 库 | 已纳入 window series（device-waydroid 0003）；真机运行时 lshal 显示 `@4.0::IAllocator/default` 有注册 |
| 运行时无法从代码层面证明 host 窗口的标题/app-id（GNOME 50 拒绝 Introspect/Eval） | HWC `setTaskWindowRoute` 记录 `TASK_ROUTE_SET task/display/component/title/app_id` 精确路由日志 | 已纳入 window series（hardware-waydroid 0002）；作为 gate3 代码级断言输入 |
| GNOME 边缘贴边/平铺（Super+Left/Right/Up）只移动 host 窗口不改变尺寸：mutter 对平铺窗口发 `XDG_TOPLEVEL_STATE_TILED_*`（无 RESIZING/MAXIMIZED），HWC 把该 configure 判为 ordinary 并忽略新尺寸，Android task bounds 不跟随 | HWC 把 TILED 状态变化视为 compositor 几何权威位（进出平铺都生效），但保持 Android 任务状态为 Normal（半屏平铺不是 Android maximize），Android 侧按平铺 bounds 调 task 尺寸 | 已纳入 window series（hardware-waydroid 0003）；真机 gate5 代码级验证：宿主窗口 resize 后 Android mBounds 按 2x 联动 |
| Android 内部启动在 host 窗口会话中被创建成 display 0 "Desk" root 上的 freeform 任务，破坏三入口共存（AviumUI 默认全屏被抢占） | ActivityStarter 的 per-task route 策略：非 trusted host 启动在默认 display 上脱离 desk root、重挂到 TaskDisplayArea 并强制 fullscreen；host 启动与同 task 导航保持 freeform；非默认 display（MiFreeform）不触碰 | 已纳入 window series（frameworks-base 0005）；gate1 旧截图证据对应的 dumpsys 实际是 `mode=freeform`+Caption，代码级 gate1 从未通过 |
| HWC HAL namespace 中 `window` 类型与 namespace 冲突 | 用显式 `struct window` 限定五处类型引用 | 窄编译发现并纳入 window series |
| 移除 bootable/recovery 后 releasetools 仍引用 `care_map_proto_py`，host 构建失败 | build/make 注释掉两处 `care_map_proto_py` 依赖 | 已纳入 release series，随本次 clean build 复验 |
| Waydroid 无 Bluetooth 应用/HAL，`resolveService` 返回 null 会抛异常 | packages/modules/Bluetooth 的 fail-soft 组件解析（记录 warning 并降级） | 已纳入 release series；分类为运行时健壮性防护，不等同于启用蓝牙功能 |
| A16 aconfig 未启用 `ACCESS_TEXT_CLASSIFIER_BY_TYPE`，ExtServices 启动抛 SecurityException | packages/modules/ExtServices 捕获异常并降级 `NO_OP` | 已纳入 release series；分类为运行时健壮性防护 |
| A16 aconfig 未启用 `ENTER_TRADE_IN_MODE`，DeviceDiagnostics 启动抛 SecurityException | packages/apps/DeviceDiagnostics 捕获异常并跳过 trade-in 启动 | 已纳入 release series；分类为运行时健壮性防护 |
| AviumUI 的 Quickstep“上滑悬停进小窗”手势是死代码：`persist.avium.launchergesture` 默认关闭，且 `CUSTOM_GESTURE_TRIGGER_THRESHOLD = 3.5f` 超过 `mCurrentShift` 上限（clamp 到 `mDragLengthFactor`，平板约 1.3–1.7）永远不可达；即使触发，`onAviumFloatWindowGesture` 走框架 PopUp（mode 101）而不是 FreeformService 原生小窗 | Launcher3 补丁：阈值降到 1.1（超过完整多任务、仍可达），手势改发 `org.avium.LAUNCHER_MINI_WINDOW` 广播进 FreeformService/MiFreeform 圆角原生小窗；device-waydroid 默认 `persist.avium.launchergesture=1` | 已纳入 window series（Launcher3 0001 + device-waydroid 0004）；locked replay r7 已验证，需真机手势复验 |

这些条目的精确 patch 路径和完成 tree 以 series JSON 为准；历史因果和日志交叉核对可见 [`docs/FIXES.md`](FIXES.md)。

## 配方/构建脚本修复

以下修复属于可复现输入的正式修正，已在 `scripts/`、`manifests/` 和 `patches/a16/` 中落地，并以本地自检通过：

- cts 与 prebuilts/misc 的 lock revision 原来是 tag 对象 SHA，repo 检出时剥壳成 commit，导致 HEAD 校验不一致；现在 lock manifest 与 lock JSON 统一固定为剥壳后的 commit（`0d0154…`、`28b423b…`）。
- `normalize-a16-source.sh` 的 repo sync 显式使用 `--no-tags`，避免 cts 的损坏 tag 引用（2655 条）阻塞 fetch；损坏 tag refs 已从 `packed-refs` 移除并备份。
- `check-repro-inputs.py` 的 `git_status` 忽略父项目下嵌套 repo 项目目录（如 `vendor/extra/init`），避免把 manifest 独立项目误判为 dirty。
- `avium-a16.sh` 的 host 库查找同时匹配普通文件与符号链接（prebuilts 中的 `libncurses.so.5` 是指向 gcc sysroot 的链接）；build pipeline 先 `cd` 到 AOSP 根目录，且整个 envsetup/lunch/m 阶段保持 `set +u`。

## 构建环境修复

- Ubuntu 24.04 所需 ncurses5/tinfo5、Meson、glslang 和 Python 模块。
- Mesa 构建优先使用系统 Python，避免 AOSP 内嵌 Python 缺少 `packaging`/`mako`。
- 对 Mesa/WebView 的五个 Git LFS 对象按 lock 中 size/SHA-256 检查。

这些属于 Docker/宿主或输入准备，不应伪装成 Android 运行时源码行为。

## 临时止血与运行态约束

清理 stale overlay、替换镜像后重启 Waydroid container、以及曾经的 Bluetooth、ExtServices、DeviceDiagnostics `disable-user` 操作，只能作为诊断或临时止血。它们没有被写入正式 A16 recipe，也不能作为启动成功的必要未记录条件。Bluetooth/ExtServices/DeviceDiagnostics 的崩溃防护已经以正式 patch 形式纳入 release series（见上表），与 `disable-user` 这类未记录止血不同。

## 证伪实验

以下方案排除出正式设计：旧 `services.jar` 热补丁、叠加式 Avium APK/smali 链、RawName/包名/Caption 顺序推断 task、substring 黑名单、固定 min/max 尺寸、按 bounds/display 变化迁移 task、全局 `forceResizable`，以及 `set-window-mode.sh` 的 android/compat/native 三选一模式。native 黑屏实验和旧镜像也不是产品入口。具体文件索引见 [`docs/ARCHIVE.md`](ARCHIVE.md)。
