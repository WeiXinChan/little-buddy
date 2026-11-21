## 本地模拟 APK 的 Android 界面测试

在个人 Mac 上使用 JDK 17 和 Android SDK（Android 36、Build Tools 35.0.0、Platform Tools），连接已授权 USB 调试的 OPPO。测试时保持设备解锁、应用窗口全屏。选择单个设备，避免应用安装到其他连接设备。测试包和应用包须从同一次构建产出。已有其他调试证书签名的 `com.littlebuddy.sim` 时，安装会失败。可换专用测试设备，或在确认可以删除该应用的本地数据后卸载旧包。

```sh
export ANDROID_HOME=/path/to/Android/sdk
export PATH="$ANDROID_HOME/platform-tools:$PATH"
java -version
./gradlew --no-daemon --max-workers=2 --console=plain :app:assembleDebug :app:assembleDebugAndroidTest

adb devices -l
export ANDROID_SERIAL=YOUR_DEVICE_SERIAL
adb shell getprop ro.product.model
adb shell getprop ro.build.version.release
adb shell getprop ro.build.version.sdk
adb install -r -g app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb shell am instrument -w -r \
  -e class com.littlebuddy.SimActivityTest \
  com.littlebuddy.sim.test/com.littlebuddy.SimUiRunner > android-ui-report.txt
cat android-ui-report.txt
```

报告应有五个通过用例和 `OK (5 tests)`。记录提交 SHA、两个 APK 的 SHA-256、设备型号、Android/API、执行命令及报告。分享前去掉设备序列号。服务器构建须使用仓库的 `scripts/with-build-lock`。当前未连接设备，界面执行和报告均待验证。

测试 runner 在测试进程里替换音频、回复与时钟，仍执行正式 Activity 的窗口布局、触摸派发、按钮处理、状态渲染和 Kotlin 协调器。五个用例验证实际窗口横屏、开始和手动结束、播放归还后计数与续听、录音和等待中停止、播放中停止及延迟释放、取消后的旧录音/回复/播放回调，以及首段前和续播等待超时的界面提示。另用 JVM 测试覆盖虚拟时钟超时和乱序。设备麦克风、扬声器、音频焦点、权限弹窗、锁屏、停止至静音以及童声表现由人工真机验收记录。

### OPPO PKW110 收音与端点对照

用户通过 Mac 安装 `fbc75bc` 的成对 APK。麦克风权限需在系统设置手动授予，之后 instrumentation 报告 `OK (5 tests)`。近讲时手动和自动结束均可听到音量正常的提示音，桌面距离不易触发。录音中停止后回待机、无迟发音或自动续听，重开正常。锁屏结束互动，解锁后待机并可重开。用户随后确认是「稍微停顿就嘟」，发生在句中短暂停顿。具体延迟、距离及停顿时长均未测得，桌面收音尚未通过验收。仅记录描述，无原始音频。

旧实现对 `VOICE_RECOGNITION` 的每次非阻塞读取使用固定 600 PCM16 RMS 门限，单次过门限即可启动语音，之后每个低于门限的样本都计入 900 ms 尾静音。这样既可能漏掉整句，也可能先识别到较响的片段、随后把同一句的轻声部分计为静音。旧界面 instrumentation 用假音频和时钟，无法定位这类输入或判断 OPPO 的增益和音源处理。新包保留 16 kHz 单声道 PCM16 和相同音源以便对照。

新实现将短读拼成 20 ms 窗口并去除直流偏置，取前 160 ms 的最低窗口 RMS 初始化噪声底。首段语音需连续 80 ms 超过 `max(90, 2.5 × 噪声底)`。触发后固定噪声底并按 `max(60, 1.6 × 噪声底)` 判断续讲，连续 80 ms 可重置尾静音，尾静音候选值为 1500 ms，给 3–5 岁儿童句中思考预留时间。若临近到点有续讲候选，最多等其完成 80 ms 确认，短脉冲消失后可结束。3 秒无任何正长度读数和从打开请求起 20 秒总时限均按轮次隔离。空轮提示后回待机。调试包仅在屏幕显示当前 RMS、语音判断、耗时及最近结束原因和耗时，离开前台清空，无持久化与上传。

能量规则假设开头有短背景且背景相对稳定。校准期间立即持续开口、突然变响的持续环境声、较弱音节、设备降噪与自动增益均可能影响结果。JVM 用小段合成 PCM 和虚拟时钟覆盖检测与计时逻辑，实际麦克风和童声效果仍由真机验收。

1. 在 Mac 上先对每版的成对 APK 运行 `shasum -a 256 -c <该版校验清单>`，按本页命令安装同一次构建的应用和测试包，再记录仪器报告。若权限对话未出现，到系统设置查看并记录授权状态。
2. 用原 `fbc75bc` 和本次版本分别做人工对照。保持同一 OPPO、手机朝向、桌面、说话人、固定短句和大致音量。量取近讲和实际桌面距离并记录厘米数，各做至少五轮。每轮先静候约半秒，再读完整句；另做立即开口的对照。
3. 在安静与日常背景下分别测试连续轻声、句中分别停约 0.5、1.0、1.2 秒再续讲、真正句末静音、静默和一次短噪声。记下是否进入有效语音、句中是否嘟、完整说完到嘟的时间，以及静默或短噪声是否被当成语音。用新包屏幕记下大致 RMS、判断、结束原因与耗时。分别复测主动结束、停止、锁屏和重开。每个距离记录成功次数及异常，避免采集录音或记录原始语句。
