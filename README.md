# AviumUI × Waydroid (Android 16 arm64)

把 [AviumUI](https://github.com/AviumUI)（LineageOS 23.2 / Android 16 QPR2）构建成 Waydroid 镜像，跑在 Xiaomi Pad 6S Pro（arm64, sm8550 主线内核）上。

这个仓库是**配方**，不是源码树。AOSP 树（275G）和构建产物（79G）不在这里，靠脚本 + manifest + 补丁复现。

> **2026-08-06 接手审计：** AviumUI A16 arm64 的编译与启动已经打通；Linux 窗口集成仍是实验态，当前源码、构建产物和平板安装态不一致。新的事实基线、实施顺序与回滚见 [plan.md](plan.md)，已验证问题见 [BUGS.md](BUGS.md)。`docs/WINDOWING.md` 和 `docs/ISSUES.md` 保留 8 月 4 日前的历史判断，不作为当前实施依据。

> **构建硬阻塞：** 当前禁止在已有 `/build` 工作树运行 `scripts/patch-and-build.sh`。脚本会执行 `repo sync -l -c` 与 `git reset --hard`，会覆盖接手现场；下方端到端流程是历史流程，完成 `plan.md` 阶段 1 重写前不可直接重放。

## 现状

镜像已构建成功并在平板上启动到 launcher 桌面。图形管线（surfaceflinger / system_server / gralloc）打通，触控输入栈正常。

**镜像状态（2026-08-04）**：
- 可运行基线：`system.img` md5 `7a4b98eb`（desktop=true，AviumUI 能显示；应用窗口 caption、full UI 与 resize 仍有 `BUGS.md` 中的确认问题）
- 实验版：`system.img` md5 `49c3f547`（desktop=false 重编，**黑屏**——根因是重编后 SF 要求 Composer3，vendor 只有 Composer2.4，与 desktop 改动无关）
- 构建机保留：`system.img.pre-desktopoff`（旧可用版）+ 当前构建产物

**窗口模式状态**：当前还未达到官方 A13 的“一项 Android task 一个 Linux 窗口”；见 [plan.md](plan.md)。

当前 Bug 清单见 [BUGS.md](BUGS.md)。

## 端到端流程

```
┌─ 构建机 (x86_64, ≥16 核, ≥23G 内存, ≥120G 磁盘) ────────────┐
│ 1. docker build -f docker/Dockerfile -t avium-build .       │
│ 2. repo init AviumUI manifest → 放入 manifests/waydroid.xml │
│    → repo sync                                              │
│ 3. [历史/禁用] scripts/patch-and-build.sh                    │
│ 4. [仅当前现场续编] scripts/resume-build.sh                  │
│    → lunch lineage_waydroid_arm64_only bp4a userdebug       │
│    → m -j8 systemimage vendorimage                          │
│ 产物: out/target/product/waydroid_arm64_only/{system,vendor}.img │
└─────────────────────────────────────────────────────────────┘
                            │ rsync (~20MB/s)
                            ▼
┌─ 平板 (arm64, waydroid 1.6.3, GNOME Wayland) ───────────────┐
│ 5. 停 session → 换 /var/lib/waydroid/images/*.img            │
│ 6. 清 overlay 陈旧文件（关键！见 docs/FIXES.md #stale）      │
│ 7. 应用宿主侧图形修复 (host/)                                │
│ 8. waydroid session start                                   │
└─────────────────────────────────────────────────────────────┘
```

关键约束：
- lunch **必须**用 A16 三段式 `lunch <product> bp4a userdebug`，旧两段式报 `Argument missing`
- ninja 用 `-j8`，23G 内存跑 `-j18` 会 OOM
- `repo sync -l` 会抹掉 detached HEAD 上的补丁提交（历史上发生过一次）

## 目录

| 路径 | 内容 |
|---|---|
| `docker/` | 构建容器（含 ncurses5 / meson / glslang / python 模块等环境修复） |
| `manifests/waydroid.xml` | local manifest：移除 50 个 qcom SoC 项目 + cuttlefish/trusty/openwrt |
| `scripts/resume-build.sh` | 历史现场续编脚本；会直接改源码和清理部分 generated intermediates，不是干净复现入口 |
| `scripts/patch_appop.py` | AppOpService 修复（跳过 flag 关闭但有 app op 的权限） |
| `scripts/archive/` | 补丁冲突排查期的一次性脚本，留档 |
| `patches/` | 树内源码改动导出（**部分待补，见 patches/README.md**） |
| `host/` | 平板宿主侧配置与二进制 |
| `docs/` | 修复因果链、机器拓扑、参考仓库、遗留问题 |

## 文档

- [docs/FIXES.md](docs/FIXES.md) — 12+ 处修复各自的根因与依据（最有价值的部分）
- [plan.md](plan.md) — 2026-08-06 现场重估、窗口方案、迁移与验收计划
- [BUGS.md](BUGS.md) — 当前 Bug、证据与过时结论勘误
- [docs/WINDOWING.md](docs/WINDOWING.md) — 2026-08-04 历史窗口研究（已被 plan.md 更新）
- [docs/TOPOLOGY.md](docs/TOPOLOGY.md) — 机器、路径、常用命令
- [docs/REFERENCES.md](docs/REFERENCES.md) — 参考仓库 URL + commit
- [docs/ISSUES.md](docs/ISSUES.md) — 2026-08-04 前的历史遗留问题

## 历史资料

早期会话转储（~1.9MB）未纳入本仓库，留在 `~/Lab/Bridge/Src/test/aviumui-waydroid/`：
`ANALYSIS.md`、`handoff2.txt`、`research/Handoff.txt`、`2026-08-02-*.txt`
