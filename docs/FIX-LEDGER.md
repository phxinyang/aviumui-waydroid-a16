# 修复账本

本账本把“可以进入正式 recipe 的源码修复”和“只能帮助一次构建或运行诊断的措施”分开。正式条目必须在 [`patches/a16/release-series.json`](../patches/a16/release-series.json) 或固定输入中可重放；当前没有 clean build 或真机结果的条目不能写成已验收。

> 发布说明：`evidence/` 和 `archive/` 是本地审计包，按仓库发布策略被 `.gitignore` 排除；其中链接不能作为 GitHub 发布包内的可用文件。

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
| AviumUI 的 Quickstep“上滑悬停进小窗”手势是死代码：`persist.avium.launchergesture` 默认关闭，且 `CUSTOM_GESTURE_TRIGGER_THRESHOLD = 3.5f` 超过 `mCurrentShift` 上限（clamp 到 `mDragLengthFactor`，平板约 1.3–1.7）永远不可达 | Launcher3 补丁只降阈值到 1.1，落地保持官方 `avium-16.2`：`startActivityFromRecents` + `launchWindowingMode=101`（同任务进 PopUp 钉住窗，102 才有系统白条）；device-waydroid 默认 `persist.avium.launchergesture=1`。recents“自由窗口”/气泡仍走 MiFreeform | 已纳入 window series（Launcher3 0001 + device-waydroid 0004）；手势不得再改发 `LAUNCHER_MINI_WINDOW` |
| 桌面 Caption/DecorContainer 给所有 freeform 任务和桌面全屏任务都画窗口栏，内部应用（全屏/小窗）也被画上“窗口栏”，违反“只有 Linux 桌面 host 应用有窗口栏、其余保持 AviumUI 原版”的共存契约 | `AppHandleAndHeaderVisibilityHelper.allowedForTask` 只对 `isWaydroidHostWindow` 任务返回 true；`ActivityStarter.updateWaydroidHostWindowRoute` 同时放行显式 PopUp 101/102（不被强制全屏） | 已纳入 window series（frameworks-base 0006）；locked replay r8 已验证，需真机复验 |
| recents“自由窗口”（AOSP freeform 启动）打开的 freeform 窗口被 0006 一并隐藏 Caption，变成“无顶栏、内容可点、但拖不动也调不了大小”的光板窗口 | 0006 的门控加 freeform 豁免：非宿主任务只有 freeform 保留标题栏（`windowingMode != FREEFORM` 才返回 false），全屏/小窗仍无窗口栏 | 2026-08-15 修正 0006（构建机 `7cdfdab3`） |
| 关掉默认屏 Desk 后，`shouldShowAppHandleOrHeader = allowedForTask && allowedForDisplay`，`allowedForDisplay` 因 `config_canInternalDisplayHostDesktops=false` 恒为 false，freeform 豁免只过了 `allowedForTask`，自由窗口依然无装饰拖不动 | 0006 在同一 helper 的 `shouldShowAppHandleOrHeader` 对 `WINDOWING_MODE_FREEFORM` 直接放行（跳过 display 门控），恢复官方 freeform caption，不重开 Desk | 2026-08-15 构建机提交 `7374b733`；增量编译中（556 步），待真机复验 |
| UU 远程在 Waydroid 里卡“初始化连接”：`/vendor/etc/media_codecs.xml` include 的 `media_codecs_c2.xml` 不存在（只有 `media_codecs_google_c2.xml`），MediaCodec 列表解析为空，H.264 编码器不可用；screenrecord 在 `Configuring recorder for video/avc` 处实测挂死，UU streamer 每次停在 `create room signal server size:3` | device/waydroid `device.mk` 补一条复制规则，把 google C2 列表同时装成 include 引用的 `media_codecs_c2.xml` | 已纳入 window series（device-waydroid 0008）；增量编 vendor 中，待真机 `screenrecord` 出非空文件 + UU 过“初始化连接”复验 |
| 修好 xml 后 screenrecord 仍永久挂死：`MediaCodecList::GetBuilders()` 无条件加入 `OmxInfoBuilder`，其 `IOmxStore::getService()` 在镜像没有 OMX HAL 时按 HIDL 默认**无限重试**（logcat 上万条 `IOmxStore/default ... Trying again`），所有 MediaCodec 初始化都被卡死，与 ccodec/xml 无关 | frameworks/av `OmxInfoBuilder.cpp` 改用 `tryGetService()`（服务不在立即返回 null → OMX 段跳过，走 C2 软编解码） | 2026-08-15 构建机提交 `c74523e6`，已纳入 release-series（fixes/frameworks-av/0001）；增量 109 步部署后 screenrecord 不再挂死，编码器可初始化 |
| screenrecord 不再挂死但录 0 帧：`c2.android.avc.encoder` 能创建（`C2SoftAvcEnc Params ...`），但 3 秒内无输入帧——`SurfaceFlinger: [ScreenRecorder] getUniqueId: Invalid operation on virtual display`，VirtualDisplay（screenrecord/MediaProjection 同路径）采集不产帧；静态 `screencap` 正常 | 待查：Waydroid SurfaceFlinger 虚拟显示采集管线 | 未修复；UU 流媒体（MediaProjection）同样依赖此路径，是“初始化连接”最后一层阻塞 |
| UU 视频栈执行层全坏（软 codec2 store 零组件、`ccodec=0` 走不存在的 OMX、screenrecord 0 帧） | 根治路线 v4l2_codec2 + 宿主 qcom-iris：vendor 集成 `android.hardware.media.c2-service-v4l2` + `libc2plugin_store`，装含 `c2.v4l2.avc.encoder/decoder` 的 `media_codecs_c2.xml`，`media.c2.hal.selection=aidl` 选 AIDL store，`.rc` 加 camera 组，`ro.vendor.v4l2_codec2.*.supported.h264=true` 注册组件，放宽编码器尺寸/码率限制 | 2026-08-16 构建机提交 device-waydroid `082b0a0`/`6566fa9`/`30fab8f`/`b9e2526`/`24a65a4` + external/v4l2_codec2 `47b493e`；store 已注册且列出 c2.v4l2 编解码器。**剩余阻塞**：`CreateInterfaceByName(c2.v4l2.avc.encoder)` 挂起（v4l2 服务打开/协商 iris 编码器不返回，5s 超时后 ffmpeg store 报 unknown，组件被 Codec2InfoBuilder 跳过）→ MediaCodec 回退软编码 → seccomp SIGSYS（`sched_setaffinity` 被 mediacodec.mesa.policy 拦截）崩溃 → 0 帧。需查 iris 驱动 V4L2 协商/缓冲 |
| UU 编码链路最终验证（2026-08-16）：qcom-iris 编码器在干净会话下完全可用。用独立 V4L2 探针（MMAP/DMABUF、1280x720/3048x1972、data_offset、VBR/PREPEND/crop 全组合）在平板直接驱动 `/dev/video18`，全部正常产出 H.264；`ENCODER_CMD(START)` 返回 EBUSY（streamon 已启动会话，无需 START）。Android 侧之前“输出 DQBUF 全 0 字节”的结论来自 strace 顶层 `bytesused=0`（MPLANE 缓冲顶层字段本就恒 0，不代表 plane 字节数），是误判；真正问题是 8/15 SIGSYS 崩溃遗留的陈旧 v4l2 服务/固件会话状态。全量重启后 screenrecord 连续 7+ 次产出合法 H.264（SPS `67 42 80 32`），UU 的“初始化连接”编码阻塞解除 | 无需代码修复；已把 v4l2_codec2/stagefright-plugins/minigbm/device-waydroid 的 UU 提交抽进 recipe（见下） | 已验证：`screenrecord --output-format=h264` 多次非空；日志 `CCodecBufferChannel: Ignoring stale input buffer done callback: last flush index=0, frameIndex=0` 为 A16 上游同逻辑，不阻塞编码 |
| recipe 同步（2026-08-16）：windowing 系列 `frameworks/base` expected_tree 更新为构建机 HEAD tree `c5e2f0bf…`（本地 0001-0009 经 check-only 验证恰好产出该 tree，之前字段是旧值）；`device/waydroid/waydroid` 补 0009-0014（v4l2_codec2 集成 5 提交 + disable veiled resizing），expected_tree `1fb1e283…`；release-series 补 `build/soong` 0004（rustc_wrapper 可执行位）、`external/minigbm` 0002（CPU 锁门禁）、新增 `external/v4l2_codec2`（8 提交）、`external/stagefright-plugins`（3 提交），全部经 worktree 回放验证 tree 匹配 | 已纳入 recipe | 自测 `test-apply-a16-windowing-patches.py`/`test-check-repro-inputs.py` 通过 |
| UU 硬解路线（2026-08-16 后半程）：UU 远程“性能差”根因是 HEVC 软解。v4l2 store 原本只注册了 H264 组件（`decoder.supported.hevc` 未开），且 UU 内嵌 WebRTC 的选择逻辑把 `c2.ffmpeg.*` 也当作“硬解”并优先选它。三步修复：① device-waydroid 开 `ro.vendor.v4l2_codec2.decoder.supported.hevc` + media_codecs_c2.xml 注册 `c2.v4l2.hevc.decoder`；② 修 v4l2_codec2 解码器初始化 bug：`android::ui::Size` 默认 `{-1,-1}`，S_FMT 变成 UINT_MAX 尺寸，iris 驱动返回 0x0 后 REQBUFS 全 EINVAL，`setupInputFormat` 改传 `ui::Size(0,0)`；③ 8 Gen 2 构建隐藏 ffmpeg 的 h264/hevc 软解（stagefright-plugins `shouldEnableCodec` 按 `ro.vendor.v4l2_codec2.hardware-video` 跳过），UU 只能选 v4l2。日志确认 v4l2 HEVC 解码器进入 `Idle => Decoding` 并切到 3840x2160，无报错；用户实测 UU 明显不卡了 | 构建机提交：device-waydroid `7ef5839`/`c9282d2`（HEVC 注册+XML 顺序）、stagefright-plugins `98c8400`、device-waydroid `a52677c`+`3a4c841`（隐藏 ffmpeg + rank）；v4l2_codec2 `69939c3`（Size(0,0)） | 已部署（vendor `aea5aa7de…`）；recipe 待同步这几笔提交。注意：隐藏 ffmpeg h264/hevc 是“专门适配 8 Gen 2”的取舍（非 iris 设备需关掉 `hardware-video` prop 恢复软解），UU 不兼容时仍可回退 WebRTC 内置软解 |
| 容器一直跑 8-14 旧系统导致所有系统侧修复不生效：waydroid `/` 是 overlay，upper 层 `overlay_rw/system/system/` 残留多套一层的旧 SystemUI/framework oat 遮蔽新镜像 | 停容器后把陈旧遮蔽目录移到备份（`stale-overlay-system-shadow-20260815`），容器重启后新镜像生效 | 2026-08-16 已处理；此后 freeform caption、OMX 修复、回归修复均实际生效 |
| freeform 放行分支把虚拟显示上的 MiFreeform 小窗/气泡也加了 caption（回归） | `shouldShowAppHandleOrHeader` 的 freeform 提前返回限定 `displayId == DEFAULT_DISPLAY && !isBubble()` | 已纳入 0006（构建机 `66d439b7`），部署后默认屏 freeform 仍出 caption，虚拟显示/气泡恢复无 caption |
| 平板默认 display 是 3048×1972 横屏但仍报 `rotation=0`。原版 AviumFreeWindow / 官方 PopUp 按 `ROTATION_90/270` 当横屏，白条和卡片会按竖屏算 | 不再改官方旋转、默认 bounds 或退出 windowing mode。这些补偿（旧 0007 remap / 0008 landscape helper / 0009 改 bounds）已从 window series 撤掉，PopUp 源码回到 AviumUI | 已撤出 recipe。平板 `ROTATION_0` 宽屏上的官方几何偏差仍在，不能再靠改 Avium 算法掩盖 |
| host 任务进 101/102 后仍在 display 0，桥接会给小窗套 Linux 标题栏 | 进入官方 PopUp 时只清 `isWaydroidHostWindow`，不改 PopUp 尺寸/旋转/退出路径 | 已纳入 window series（frameworks-base 0007 drop-host-route） |
| 官方 102 用 leftover 裁 9:16，横竖屏看 `DisplayContent.getRotation()`。Desk leftover 和 `ROTATION_0` 不是 Avium 输入 | 不再改官方 leftover/旋转/退出。关掉默认屏 Desk，让官方算法吃到全屏 leftover | 已纳入 window series（device-waydroid 0005 Desk-off + 0006 盖过 Lineage desktop）。旧 leftover/旋转补偿已撤出 |
| 关掉默认屏 Desk 后 `DesktopTasksController.onInit()` 不再跑，Linux host 桥一起停 | 在 `canEnterDesktopMode=false` 时单独 `waydroidTaskWindowStateBridge.start()` | 已纳入 window series（frameworks-base 0008 host-bridge） |
| 关掉 Desk 后 SystemUI `DesktopFirstRepository` 仍注册 listener；`DesktopFirstListenerManager` 为空就抛，KeyguardService 崩循环，app 层被藏成黑屏 | `register/unregisterDesktopFirstListener` 在 manager 为空时直接返回 | 已纳入 window series（frameworks-base 0009）；需增量编 SystemUI 后真机复验 |
| 点 Waydroid / `show-full-ui` 后窗口黑屏：hybrid 在 `multi_windows=true` 时永远接管，A16 SF 只 client-compose，hybrid 贴空的 `FRAMEBUFFER_TARGET` | `active_apps=Waydroid` 走官方 `non_compositing_full_ui_mode`；0004 仍把 framebuffer 贴到 hybrid carrier | 已纳入 window series（hardware-waydroid 0004+0005）；真机已能建 xdg，像素仍黑是下一条 |
| 宽屏 Waydroid `ROTATION_0` 让官方 leftover 可能仍是旧的竖屏 9:16 | 保持官方 PopUp 几何：进入 101/102 时不再用当前 display 矩形覆盖官方 leftover。临时补丁 0010 已从 window series 撤出（移入 `a16/frameworks-base/superseded/`），`PopUpWindowController` 回到官方源码 | 2026-08-15 起回退：series.json expected_tree 更新为 `84181834…`；白条仍按官方 `ROTATION_0` 画在卡片下方，宽屏上官方 9:16 偏差作为原版行为保留 |
| `persist.waydroid.multi_windows=false` 保住 full-UI，但 Linux 单应用被做成最大化 surface，GNOME 顶栏拖不动 | 产品默认改回 `true`。点 Waydroid 仍走 hardware-waydroid 0005 官方 full-UI；host `.desktop` 才走 hybrid xdg。Desk 保持关 | 已纳入 window series（device-waydroid 0007）；运行态可先 `setprop`，产品默认要编进 system.img |
| Desk 关闭后 Android Caption 画了层，但 `DesktopModeWindowDecorViewModel` 不接拖动，GNOME 窗口又是 `decorated=false`，顶栏拖不动 | 0006 请求 `zxdg_decoration` SERVER_SIDE 被 mutter 忽略；0007 改为 HWC 检测 host caption 条内的左键按下并直接 `xdg_toplevel_move`，不把该次按下转给 Android。不重开 Desk，不改官方 PopUp | 已纳入 window series（hardware-waydroid 0006+0007）；`.128` 真机 Via 顶栏拖动已复验 `TASK_XDG_GESTURE ... reason=host-title-strip` |
| `.3.131` 上 waydroid 内光标完全不显示：SF 光标层（Sprite#45/#46）每帧都在、以 CURSOR flag 走 `apply_cursor→wl_pointer_set_cursor`，但宿主没光标。移动鼠标时 composer 进程每次都报 `Invalid reference (resource_info() called on unregistered handle)`（minigbm gralloc），静止/纯画面刷新不报 | 光标 sprite buffer 在 A16 栈上没经过 composer 侧 import，HWC 的 shm 路径（`egl_render_to_pixels`）向 gralloc 查 buffer info 时 handle 未注册 → EGL image 建不出来 → 光标 surface 空内容。修复：`get_wl_buffer` 对 shm buffer 先用 `GraphicBufferMapper::importBufferNoValidate` retain 进本进程 gralloc，EGL/mapper 读取用 `imported_handle`，随 buffer 析构释放 | 已纳入 window series（hardware-waydroid 0008）；增量 vendor 编译 80s，部署后 10 次鼠标移动 `Invalid reference` 从 10 条降到 0 条，新 `.so` 已确认加载 |
| Linux 桌面下 host 应用窗口最大化/全屏后，顶部小白条（Android Caption）拖动失效：`begin_host_titlebar_move` 的 caption 命中测试要求 `pointer_display_y∈[task_top, task_top+108)`，但 host 窗口的 host→Android scale 来自全局 `display->scale`（fractional-scale 监听器只在 calibration 触发一次且每窗口互相覆盖，实测 1/2/4 飘动），最大化时 bounds 桥又保留 freeform 原点（`1061,158-4109,2130` 溢出显示区）→ 指针映射与呈现的 caption 层不一致，命中失败 | HWC 改为 per-window scale：任务窗口的 scale 由 task bounds/configured host size 几何推导；指针/触摸/手写笔映射用所属窗口的 scale（`layerFrame.scale`，0 回退全局）；最大化时 bounds 请求归到 `0,0-3048,1972` 并记录 `last_host_maximized`；保留 caption 命中拒绝诊断日志 | 已纳入 window series（hardware-waydroid 0009，构建机 `d2316e4`）；真机验证：最大化→拖顶部白条→`TASK_XDG_GESTURE api=move reason=host-title-strip`→`max=0` 还原 freeform 窗口，bounds `0,0-3048,1972` |
| recipe 落后部署两笔修复（重做镜像会丢）：本地 0006 的 FREEFORM caption 放行无条件（缺气泡/虚拟显示豁免 `66d439b7`），且 window series 完全没有 `ShellDesktopStateImpl.isEligibleWindowDropTarget` 改动（`56000324ce88`，desk-off 默认屏自由窗口拖动） | 新增 frameworks-base 0010（`66d439b7` 原样）与 0011（`56000324ce88` 原样）；release-series 补 `manual/build-soong/0003-rustc-wrapper-anchor-pwd-strip.patch`（增量构建退化为全量的根因修复此前未被清单引用），并把 `test-a16-series.py` 的 release patch 计数从旧的 185 更新为实际 202 | 已收口：frameworks-base 从 base_tree 用本地 0001-0011 重放产出 `c5e2f0bf`（check-only `verified`）；构建机全项目 check-only `ok:true`；本地测试全过 |
| Linux host 应用进全屏后，拖顶部小白条只移动窗口、缩不回带窗口栏的自由窗口：窗口栏全屏键走 `moveToFullscreen` 把任务切成 `WINDOWING_MODE_FULLSCREEN`，而 `WaydroidTaskWindowStateBridge` 的状态门只认 FREEFORM → 全屏任务从不发布 MAXIMIZED，HWC `last_host_maximized=false`，caption 拖动只执行 `xdg_toplevel_move` | bridge 把 FULLSCREEN 的 host 任务视为 maximized：`handleTaskInfo` 检测 FREEFORM→FULLSCREEN 转变时发布 `MAXIMIZED`（带 `lastNonFullscreenBounds`）；HWC 收到 NORMAL（拖白条还原）时 `DesktopTasksController.restoreWaydroidHostTaskFromFullscreen` 用 WCT 把任务切回 FREEFORM + 还原 bounds（默认屏 desk-less，走不通 desk 还原路径），再 ack 状态；`applyHostBoundsRequest`/`publishRequestedState`/`getCurrentState` 同步放开 FULLSCREEN | 已纳入 window series（frameworks-base 0015，构建机 `fe3d26ce`）；后续 0016/0017 仍经回放，当前 frameworks/base expected tree 为 `d47c1029`；system `a0bf8907` + vendor 不变已部署，容器重启后 boot_completed=1 |
| SystemUI 重启后 host 窗口桥可能保留已失效 callback，HWC 仍存活导致 Framework 不触发重新注册 | Framework 在 HIDL state 返回失败时清空 service、清理 pending bounds 并走既有 reconnect；HWC 在 callback 已失效时让 `setTaskWindowState` 返回失败；断连期间 retired window 列表在 Wayland sync 失败时交换并释放 | 已纳入 window series（frameworks-base 0016、hardware-waydroid 0016）；hardware expected tree `0559a57c`，需真机 SystemUI restart 回归 |
| Framework freeform caption 判断残留 `FreeformDbg` 调试日志 | 删除该日志，保留正式 caption 路由判断 | 已纳入 window series（frameworks-base 0017）；需随 clean build 复验 |

这些条目的精确 patch 路径和完成 tree 以 series JSON 为准；历史因果和日志交叉核对可见 [`docs/FIXES.md`](FIXES.md)。

## 配方/构建脚本修复

以下修复属于可复现输入的正式修正，已在 `scripts/`、`manifests/` 和 `patches/a16/` 中落地，并以本地自检通过：

- cts 与 prebuilts/misc 的 lock revision 原来是 tag 对象 SHA，repo 检出时剥壳成 commit，导致 HEAD 校验不一致；现在 lock manifest 与 lock JSON 统一固定为剥壳后的 commit（`0d0154…`、`28b423b…`）。
- `normalize-a16-source.sh` 的 repo sync 显式使用 `--no-tags`，避免 cts 的损坏 tag 引用（2655 条）阻塞 fetch；损坏 tag refs 已从 `packed-refs` 移除并备份。
- `check-repro-inputs.py` 的 `git_status` 忽略父项目下嵌套 repo 项目目录（如 `vendor/extra/init`），避免把 manifest 独立项目误判为 dirty。
- `avium-a16.sh` 的 host 库查找同时匹配普通文件与符号链接（prebuilts 中的 `libncurses.so.5` 是指向 gcc sysroot 的链接）；build pipeline 先 `cd` 到 AOSP 根目录，且整个 envsetup/lunch/m 阶段保持 `set +u`。
- 增量构建退化为全量（每次小改动都要 1–2h+）的根因：`build/soong/scripts/rustc_wrapper.sh` 把 depfile 里的绝对路径前缀剥掉时用了**未锚定的全局 sed**（`s|`pwd`/||g`，上游 AOSP 2025-06 的 0db933ff6 引入）。本工作区根正好是 `/build`，于是 `out/soong/.intermediates/build/make/...` 中间的 `/build/` 也被删掉，变成 `out/soong/.intermediatesmake/...`；该畸形路径被 ninja 记入 deps 日志后成为永不存在的 phony 输入，导致 `aconfig.clippy` 永远脏 → aconfig 二进制每次重编 → 所有 `aconfig-cache.pb`/flags 头重生成（`cc_aconfig_library` 无 restat）→ ART 全量级联（~2 万步）。修复：sed 改为锚定前缀 `s|^`pwd`/||`，并清掉 deps 日志里的畸形条目（让 clippy 用修复后的 wrapper 重跑一次即自动覆盖）。补丁在 `patches/a16/manual/build-soong/0003-rustc-wrapper-anchor-pwd-strip.patch`，构建机提交 `38fcf042`。副作用：修 wrapper 会让所有 rust 边脏一次（一次性 settle），ccache 上限已从 256M 提到 30G 加速后续构建。

## 构建环境修复

- Ubuntu 24.04 所需 ncurses5/tinfo5、Meson、glslang 和 Python 模块。
- Mesa 构建优先使用系统 Python，避免 AOSP 内嵌 Python 缺少 `packaging`/`mako`。
- 对 Mesa/WebView 的五个 Git LFS 对象按 lock 中 size/SHA-256 检查。

这些属于 Docker/宿主或输入准备，不应伪装成 Android 运行时源码行为。

## 临时止血与运行态约束

清理 stale overlay、替换镜像后重启 Waydroid container、以及曾经的 Bluetooth、ExtServices、DeviceDiagnostics `disable-user` 操作，只能作为诊断或临时止血。它们没有被写入正式 A16 recipe，也不能作为启动成功的必要未记录条件。Bluetooth/ExtServices/DeviceDiagnostics 的崩溃防护已经以正式 patch 形式纳入 release series（见上表），与 `disable-user` 这类未记录止血不同。

## 证伪实验

以下方案排除出正式设计：旧 `services.jar` 热补丁、叠加式 Avium APK/smali 链、RawName/包名/Caption 顺序推断 task、substring 黑名单、固定 min/max 尺寸、按 bounds/display 变化迁移 task、全局 `forceResizable`，以及 `set-window-mode.sh` 的 android/compat/native 三选一模式。native 黑屏实验和旧镜像也不是产品入口。具体文件索引见 [`docs/ARCHIVE.md`](ARCHIVE.md)。

## AviumFreeWindow APK 层修复（2026-08-16，用户确认方向）

**决策**：前两个问题（选择器启动路由、重复悬浮条）在 App 层修复（框架保持官方）。本条目区别于上面"证伪实验"排除的"叠加式 Avium APK/smali 链"——那是旧窗口工作的实验性堆叠，不是本次"把官方 APK 自身预留的官方路径接上 + 修官方 App 自身 bug"的最小修复。

**问题 1（选择器→自由窗口，已回退）**：官方 APK 选择器非气泡分支调 `launchedappforavium`（102 轻量小窗，display 0）。曾尝试把两个适配器非气泡分支改调类里预留的 `launchAppNormally`（→ FreeformService → 虚拟显示自由窗口），但用户决定**严格回官方**（选应用→102 小窗，接受跳板 App 逃逸为官方行为）。该改动已从部署 APK 撤除，相关脚本已删除（git 历史保留）。

**问题 A（几何）**：官方尺寸公式 `height = min(realH, realW)/ratio` 假设竖屏；横屏 ROTATION_0 平板算出 2032x3612 虚拟显示、2032x3048 浮窗垂直溢出。修复：`initConfig` 与 `showWindowToMini` 两处 `freeformScreenHeight` 上限为 `getRealScreenHeight()`。真机浮窗回到 677x1204。

**问题 B（双悬浮条，已回退）**：真根源是 `ForegroundService.showFloating()` 与 `KeepAliveService`（无障碍保活）各自开机加一个 54x162 悬浮窗。曾把 `KeepAliveService.showFloating()` 置空；用户决定**回官方**，改为不启用该无障碍服务（`accessibility_enabled=0`）即可单条。

**问题 C（showWindow 幂等，已回退）**：防御性补丁，未观察到实际出错；用户决定回官方，已撤除。

**问题 D（旋转方向误判，侧边栏超大窗口真根因）**：App 用 `screenRotation` 判方向（ROTATION_0/2=竖屏）。平板物理横屏（3048x2032）但报 ROTATION_0 → App 当竖屏，`getRealScreenHeight()` 返回 max(w,h)=3048、`getRealScreenWidth()` 返回 min=2032，所有自由窗口/浮窗尺寸都按这个交换值算 → 侧边栏打开的应用窗口 2032x3048 垂直溢出（用户实测 uu 远程）。修复三处：`getRealScreenHeight/Width` 直接返回窗口物理高/宽（不再按旋转交换）；`FreeformHelper.screenIsPortrait` 改为按实际宽高判断（宽>高即横屏）。真机浮窗回到 1016x1806（9:16 竖窗、居中、适配屏幕）。

**最终定版（用户拍板）**：1/3/4 全部回官方，只保留 2（官方公式 + 修正横屏检测）。`scripts/patch-avium-freeform-orientation.py` 从官方 APK 直接产出 `2a1c9eae…`（已部署平板，overlay `/var/lib/waydroid/overlay/system/system_ext/app/AviumFreeWindow/`）。归档 `out/avium-freeform-chooser-freeform-20260816/`（out/ 为 gitignore）。中间版本 `4be2ab25/23e02d61/7edca1d2` 仅存于 git/归档。

**真机验证**：开机仅 1 条悬浮条；`LAUNCHER_MINI_WINDOW` 广播启动 mark.via → 浮窗 677x1204（适配）、任务在 Display #2。侧边栏路径（ForegroundService → ChooseAppFloatingView → launchAppNormally → ACTION_START_INTENT）与广播同路径，待用户实测确认。

**环境注意**：2026-08-16 平板重启后 `/var/lib/waydroid/waydroid.cfg` 再次被清零（老毛病，备份目录已有 `waydroid.cfg.zeroed-20260810`），已从 `waydroid.cfg.bak-gralloc` 恢复（损坏文件保留为 `waydroid.cfg.zeroed-20260816`）。平板 IP 现为 `<tablet-ip>`。
