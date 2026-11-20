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

报告应有四个通过用例和 `OK (4 tests)`。记录提交 SHA、两个 APK 的 SHA-256、设备型号、Android/API、执行命令及报告。分享前去掉设备序列号。服务器构建须使用仓库的 `scripts/with-build-lock`。当前未连接设备，界面执行和报告均待验证。

测试 runner 在测试进程里替换音频、回复与时钟，仍执行正式 Activity 的窗口布局、触摸派发、按钮处理、状态渲染和 Kotlin 协调器。四个用例验证实际窗口横屏、开始和手动结束、播放归还后计数与续听、录音和等待中停止、播放中停止及延迟释放、取消后的旧录音/回复/播放回调。另用 JVM 测试覆盖虚拟时钟超时和乱序。设备麦克风、扬声器、音频焦点、权限弹窗、锁屏、停止至静音以及童声表现由人工真机验收记录。
