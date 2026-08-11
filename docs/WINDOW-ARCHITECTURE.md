# 窗口架构

## 目标与原则

窗口路由按启动来源保存为 per-task 状态，不使用需要重启的全局模式。Linux 独立窗口应接近官方 Waydroid A13：每个 host task 有明确 task ID/TID、component、标题、图标、app-id、display 和生命周期，创建一个独立 `xdg_toplevel`。AviumUI 默认全屏和 Avium 原生小窗是并存的既有体验，不能被 Linux 桥的全局开关接管。

## 三种入口

| 启动来源 | host-window token | 结果 |
| --- | --- | --- |
| Avium Launcher 或 Android 内部启动 | 无 | 默认 Android 全屏；同 task 导航不进入 Linux 独立窗口 |
| Avium 手势、气泡、原生小窗 | 无，且使用 MiFreeform display | 保持 Avium/MiFreeform 原生小窗；Waydroid HWC 忽略该 display/task |
| Linux `.desktop` 或 Waydroid host app | 有，且只作用于本次 launch | ATMS/WMS 保存 host route，HWC 按明确 task ID 创建独立 `xdg_toplevel` |

正式数据路径为 `Linux host launch -> WayDroidService -> A16 ATMS/WMS per-task state -> Task/TID surface -> Waydroid HWC -> Wayland xdg_toplevel -> compositor`。当前实现使用 descriptor 为 `com.avium.waydroid.launch.HOST_WINDOW` 的 launch cookie；WayDroidService 清除 Binder caller identity 后以 system UID 发起 freeform launch，ActivityStarter 同时验证 system UID 与 descriptor，再把 route 写入最终 leaf Task。Task 通过 `isWaydroidHostWindow` 写入 TaskInfo 与 task XML；同 task 导航继承，Android 跨 task launch 清除，进入真实非默认 display 时清除。

默认 display（display 0）的完整 route 策略由 `ActivityStarter.updateWaydroidHostWindowRoute` 强制执行：trusted host launch 与同 task 导航保持 freeform 并留在 desk root；其余所有 Android 内部启动（无 trusted cookie 的跨 task launch）必须脱离 desk root、重挂到 TaskDisplayArea 并转 fullscreen，即使 host 窗口会话正在进行。这样 AviumUI 默认全屏与 Linux 独立窗口在同一条 display 上共存。非默认 display（Avium/MiFreeform）的窗口策略完全不动。

WM Shell 只监听 TaskInfo 的 appeared/info-changed/vanished，并通过 `vendor.waydroid.window@1.3::setTaskWindowRoute` 发布 task ID、display、component、title 与 app-id。HWC 的 route map 是 external `xdg_toplevel` 的唯一分类依据；TID 只提供 task 身份，不决定来源。未 route 的 TID、Unscoped、MiFreeform 和 system layer 只进入显式 full-UI carrier。`waydroid.active_apps` 仅用于 full UI 生命周期提示，`waydroid.full_ui_active` 是独立 latch；它们不再充当 external task 集。

## 职责边界

- Framework/WayDroidService 识别启动来源、生成并消费 token、保存 task 身份。
- ATMS/WMS/WM Shell 传播 task ID 和 external-route 状态，并管理 Android task 内容尺寸。
- HWC 只消费明确 task ID，组合对应 surface，管理 buffer fd、Wayland callback、configure/ack、retirement 和 primary-child ownership；不猜来源、不迁移 Avium task。
- Linux compositor 管理外部窗口位置、焦点、最小化/最大化/恢复和关闭。
- host configure 与 Android task 更新必须按 task ID 对应，并指定单一几何权威，避免双向反馈循环。
- 使用 A16 正式 caption/task decoration layer；不继续维护自绘 GPU caption。

## 正式补丁边界

唯一 window recipe 是 [`patches/windowing/a16/series.json`](../patches/windowing/a16/series.json)，固定四个 project 的 base/expected tree 与每个 patch SHA-256。应用器 [`scripts/apply-a16-windowing-patches.py`](../scripts/apply-a16-windowing-patches.py) 先在临时 worktree 完整重放，再做 ff-only 更新；输入校验、check-only、完成态和失败恢复语义有隔离测试。locked replay 的 before/after 采集同时记录 commit HEAD 和 `HEAD^{tree}`：check-only 必须让基准 checkout 的两者保持不变且 tree 等于 `base_tree`，而临时 worktree 的重放结果由 `result.json` 中的 `expected_tree` 独立证明；[`scripts/verify-window-replay-evidence.py`](../scripts/verify-window-replay-evidence.py) 对这两个不同身份做机器检查。

设备侧只保留 HAL 1.3 manifest patch。旧 `0000-waydroid-tablet-desktop-capability.patch` 会让 secondary/freeform display 全局 desktop-first，可能接管 MiFreeform，因此不在正式 series 中。host task 由可信 per-task route 的 `forceDesktop` 分支进入 desktop，无需该全局 overlay。旧顶层 `patches/windowing/frameworks-base/`、`hardware-waydroid/` 以及多代 Python patcher 均不是正式输入。

## 保留与删除

保留并回归验证：官方 TID 身份；正确标题、图标、app-id 和 dock 分组；多应用独立窗口；host move/resize 桥接；已证明必要的 buffer fd 生命周期；Wayland callback/retirement；primary-child ownership；以及已修好的 Android PointerIcon -> HWC -> Wayland cursor 通路。

删除、归档或重写：RawName/包名/几何/Caption 顺序推断、substring 黑名单、固定 min/max、按瞬时 bounds/display 迁移、自绘 GPU caption、全局 `set-window-mode.sh` 三选一、native 黑屏产品入口、重复 patch/字符串替换器和绑定错误实现的静态测试。

## 未关闭回归门

当前不能宣称窗口重构完成。必须在同一套 framework/HWC 镜像上真机验证：三入口无需重启共存；两个以上 Linux app 的 focus/move/resize/minimize/maximize/restore/close；快速拖动、甩动、贴边、最大化/恢复无旧帧和跳位；StarNote 多 layer 反复移动/resize 无重复标题栏；物理鼠标进入、移动、PointerIcon 改变和离开保持可见性、hotspot 和宿主回退；关闭一个窗口不影响其他窗口、Avium full UI 或原生小窗。当前“平板鼠标进入 Waydroid 窗口已修好”是保留的回归门，不是待修 Bug。
