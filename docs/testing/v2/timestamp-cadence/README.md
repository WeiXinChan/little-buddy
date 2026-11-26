# 有界硬件 cadence 元数据诊断

这是 tests-only 单会话观察，不是生产录音通过，也不放宽 NativeReadLedger。保留 RC7 原 FAIL：320 frames / 20178846 ns = 15858.1913 Hz；原 15984–16016 Hz、±2 frame 小对检查的下界为 320.538674464，实际少 0.538674464 frame。当前报告只有最后一对，无法区分相邻估计抖动与持续偏移。历史另一会话的长窗口不是本会话证据。code20 原启动 FAIL 同样保留。

官方 [AudioTimestamp](https://developer.android.com/reference/android/media/AudioTimestamp) 将 nanoTime 定义为 estimated capture time；未保证每个 20ms 对符合本项目 ±2 frame。历史 [Android11 CTS AudioHelper](https://android.googlesource.com/platform/cts/+/android11-release/tests/tests/media/src/android/media/cts/AudioHelper.java) 分别检查 jitter 与长期关系，不能将历史 CTS 的容差作为 OPPO 保证或生产新阈值。AOSP 的时间戳位置选择也不证明此驱动在切换位置。

## 范围与边界

仅一个 VOICE_COMMUNICATION / 16000 / mono / PCM16 会话，申请 6400 bytes、要求实际 3200 frames；无模型、KWS、内容处理或网络。320-sample 临时数组在 read 返回后立即 finally 清零，异常亦清零。起点在 startRecording 之前，固定 3500ms、2048 timestamp API、64000 samples、256 条唯一 frame/ns trace 上限；任一上限先到即结束，不增加第二会话。JNI 不能保证物理中断，超时仍必须报告 worker/native/stop/lease 未完成，不能跳过或冒充正常。

观察器保留累计 read 数；有限窗口内按原 3200-320 frame 空间和 16016 Hz 上界估算未读预算，计入 start、read、timestamp API 耗时。该软件观测保护依赖有限窗口采样率上界假设，不是物理连续性证明或生产授权。超预算真实失败，不重标音频或增加 buffer。没有任何 PCM 进入生产消费者。

每个变化的 frame/ns 保留 API 前后 mono/boot 时间、累计读取量、相邻 delta、相对首个有效对 delta、至少 500ms 间隔 delta、旧 rate oracle 结果及异常标记。首对仅用于比较，不重置 native origin 或 read 计数。迟到 API 原返回保留并标 late；下一 API 前重新检查边界。原生产 gate 不执行，旧 oracle 拒绝只作为诊断元数据；观察结束只能为 ONE_SESSION_OBSERVATION_ONLY。JSON 仅 worker 真正 join 后读取；输出明确实际 preflight/native/cleanup 字段，不混入旧 production probe 默认字段。

## 构建与执行（root 审查后统一执行）

普通 runner 仍为 SimUiRunner；专用构建：

```sh
scripts/with-build-lock ./gradlew -Pv2Test -I app/src/androidTest/native-timestamp.init.gradle :app:assembleV2DebugAndroidTest --offline --no-daemon --max-workers=1
```

专用 runner 只精确允许列出的测试方法，以空 Application 和 target 已声明 Activity 的 test-only 替身保持 target UID 前台；不加载业务配置，不绕过家长验证。只允许 code21 target；本工具不修改主类，现有 RC7 业务 APK 不需重新构建。最终 test APK 必须核 aapt instrumentation 节点、同签名及剔除旧音频 fixtures 后的 retained entries。不得把编译当实机前台证明。

设备独占并核 RC7 hash、无活跃录音/播放/测试/草稿后，由 root 已授权执行方确认受控空闲进程再正常退出；仅明确属于受控测试遗留的 V2 空闲进程可停止，不动 V1、配置、凭证。instrument 不得自行重启未知业务。精确执行：

```sh
adb shell am instrument --no-logcat -w -r -e class com.littlebuddy.NativeTimestampCadenceTest#observeOneBoundedCadence -e nativeTimestampProbe true -e nativeTimestampCadenceDiagnostic true -e businessIdlePreflight true com.littlebuddy.sim.v2.test/com.littlebuddy.NativeTimestampRunner
```

本地 21 JVM tests 通过，含原 pair 拒绝、有限抖动与持续 drift 的受控区分、deadline/取消/清零/API cap。它们不证明硬件抖动、声学效果或生产 PASS。root 旧 8-test snapshot 的 cap 为 1024，不计入本 head 的通过分母；本 head cap 为 2048。设备未执行，原硬件 FAIL 不改变。
