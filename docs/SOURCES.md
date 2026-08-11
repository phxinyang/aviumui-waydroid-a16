# A16 来源与输入锁

## 上游来源

- 项目：AviumUI，入口 [AviumUI about](https://aviumui.org/about)。
- Android manifest：<https://github.com/AviumUI/android_manifests>。
- 分支：`avium-16.2`。
- 已锁定的 manifest repository HEAD：`981823afd5a1c3fcf740cd3b4eeeb61331ca8304`。
- 官方初始化命令：`repo init -u https://github.com/AviumUI/android_manifests -b avium-16.2 --git-lfs`。

正式复现不能让 `avium-16.2` 分支在初始化与同步之间移动，因此使用 repo 对 commit revision 的正式支持，并同时声明其 upstream branch：

```bash
repo init -u https://github.com/AviumUI/android_manifests \
  -b 981823afd5a1c3fcf740cd3b4eeeb61331ca8304 \
  --manifest-upstream-branch avium-16.2 --git-lfs
```

仓库中的 [`manifests/waydroid.xml`](../manifests/waydroid.xml) 是上次核实与构建机 local manifest 一致的来源文件，SHA-256 为 `6ae088822c13525c7de6e853ed0f3aee1d8c4054a586ca6ece5207bfe7b61197`。[`manifests/waydroid.lock.xml`](../manifests/waydroid.lock.xml) 在该内容上展开并固定全部项目 revision，SHA-256 为 `0afa95cfe28d2f86aff81cd1f9d55f5ff3588fc7e2fad9b9d18eb53b899b9902`；正式同步时把后者复制为 AOSP checkout 的 `.repo/local_manifests/waydroid.xml`。不要把构建机上的临时 manifest 当输入。

[`evidence/a16-manifest-only-20260811/`](../evidence/a16-manifest-only-20260811/) 记录了独立 `/tmp` 目录中的固定 commit `repo init` 与 lock XML 展开检查：1085 个 project 均得到 40 位 SHA revision；该检查没有运行 `repo sync`，因此不冒充源码同步或 clean build。

[`manifests/a16-recipe-lock.json`](../manifests/a16-recipe-lock.json) 是机器可检查的输入锁：manifest HEAD、local manifest hash、1085 个 project 的 base HEAD、必需命令、120 GiB 最低空闲空间和 5 个必须是完整 Git LFS 对象的文件都在其中；A16 完成 tree 由 [`patches/a16/release-series.json`](../patches/a16/release-series.json) 锁定，窗口最终 tree 与 patch digest 由 [`patches/windowing/a16/series.json`](../patches/windowing/a16/series.json) 锁定。三者共同作为 provenance 校验输入，不是 Android 源码的替代品。

## 同步边界

同步后每个 project 必须是干净 Git checkout；preflight 会拒绝 dirty manifest repository、dirty project、错误 HEAD、缺失 LFS 对象、错误 local manifest 和正在运行的 `ninja`/`soong_ui`/`ckati`。源码准备状态由 [`scripts/check-repro-inputs.py`](../scripts/check-repro-inputs.py) 检查，series 完整性由 [`scripts/test-a16-series.py`](../scripts/test-a16-series.py) 检查。

不要在已有 `/build` 现场直接执行会 sync、reset 或 clean 的旧脚本。构建机现场的保存、回滚和历史排除见 [`docs/BUILD-A16.md`](BUILD-A16.md) 和 [`docs/ARCHIVE.md`](ARCHIVE.md)。
