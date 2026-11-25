冻结供root review，放行树之前不push/CI29。此为host-only单变量模拟器后端对照，不是产品修复或VirtIO缺陷结论。

来源与已有实测

CI28 run45525063062/job138906235423，artifact14982740574 SHA16ec8b2934214564bfdb41ab2cfd961533f6d5c8c3a2a05e6123240c64938e3d：实际VirtIO SoundCard/virtio_snd、legacy/wrapper对象SHA可证，ELF BuildID和active session关联仍UNKNOWN。root/id0一次过，PA完整正文corr.997752385/SDK true读点/owned回收false过，guest122048/7.628秒峰8首秒后零、liveFAIL；九组16项过，JVM/提示新鲜度后续NOT_RUN。Capture Channel Map -1不擅释为mute；六条late-silence是有限历史窗口事件，不称解释整段零，不以参考默认当实际二进制。

本机只读核已知隐藏SDK位置，其emulator/source.properties、lib advancedFeatures及API36镜像文件都UNAVAILABLE。未下载SDK/启动AVD/probe/音源，不把缺本机SDK称支持失败根因。完整运行文件与二进制/guest证据只能由放行后的CI29取得。

参考边界

root提供的官方cmdline-options.h feature <name|-name>及main.cpp buildSoundhwParam：参考VirtioSndCard开选virtio-snd-pci，关且API>=26/x86选hda。官方prebuilt lib advancedFeatures.ini说明该feature对应VirtIO/IntelHDA，镜像advancedFeatures也有声明。

- https://android.googlesource.com/platform/external/qemu/+/emu-master-dev/android-qemu2-glue/main.cpp
- https://android.googlesource.com/platform/prebuilts/android-emulator/+/master/linux-x86_64/lib/advancedFeatures.ini
- https://android.googlesource.com/platform/tools/base/+/refs/heads/main/sdklib/src/main/java/com/android/sdklib/repository/PkgProps.java

它们只支持方案/字段定义，不证明16970787实际二进制已支持或选中了HDA。实际文件声明只是第一门，必须再有同UID/祖先/exe实际QEMU argv与guest正向card/driver双证。

精确执行与STOP顺序

1. 既有SDKmanager安装后、emulator启动前执行hda_guard.py，只读实际ANDROID_HOME下：emulator/source.properties的Pkg.Revision=37.3.10/Pkg.BuildId=16970787，emulator/lib/advancedFeatures.ini唯一VirtioSndCard=on/off；固定API36/google_apis/x86_64镜像source.properties的API/ABI/tag和其advancedFeatures同名唯一feature。每文件最多256KiB，持久化只有文件SHA/指定字段值/可用性。缺失、重复、未知值或版本不符STOP，fixture NOT_RUN。不扫描组合或替换SDK。
2. emulator原GUI/PA profile/镜像/端口/令牌设置均保留，启动参数只新增 -feature -VirtioSndCard，不改avd配置/属性/HAL文件/格式或音量。
3. 既有exact fingerprint/API36/ranchu/synthetic/私有两nullPulse门保留。M06_REQUIRE_HDA=1时M06_NATIVE_READONLY必须1；缺失或0立即STOP，不能旁路runtime_gate进入run_arm。
4. PrivatePulse原同UID/祖先、真实exe/socket/白名单PA环境全部先过后，才读取QEMU实际NUL argv，唯一soundhw必须精确hda（允许两参数或等号表示）。缺失/重复/冲突/virtio/未知值STOP，只记录hda枚举，不输出整份cmdline/env/token。显式virtio-snd device冲突也拒绝。flag存在本身不是该门证明。
5. 原NativeReadOnly.prepare仍只root一次/id0及HAL PID/UID/starttime/exe守门，native诊断UNAVAILABLE边界保留。PA前其实际root、稳定before快照、ALSA card和driver必须可用。严格要求单一HDA-Intel正向card及同card编号的/sys/bus/pci/drivers/snd_hda_intel，不能仅“不是virtio”。stillVirtIO、无卡、错driver、权限/identity失败全部硬STOP、fixture NOT_RUN，无fallback/重播/第二次root。
6. 只有全部门满足才进入原run_arm(7)/完整mic/生产Capture/KWS/Boundary，原正文SHA/16k或24k采样率、600ms零前300ms尾、8秒128000、SDK一次true、零injectAudio、必需完整monitor/实际QEMU uncorked和owned回收后false均不变。原mic矩阵+九组设备门不删除，enter过后继续原提示/新鲜度/零上传；前置STOP后的fixture/未到阶段诚实NOT_RUN。

回归与解释

host负控包括SDK文件缺失/重复/未知/错版本，实际NUL解析不泄漏token、唯一hda正控及missing/duplicate/virtio/unknown/compound值/virtio-device冲突；guest HDA卡与snd_hda_intel编号匹配正控，非HDA/无卡/virtio/错driver/root权限失败；runtime顺序、requireHDA而native flag缺失/0必须不调用run_arm。测试用合成SDK文件、Fake proof/native数据；不是本机实际37.3.10或GHA HDA证明。原75项host回归保留，最终总数见日志。

HDA若取得完整guest/live，只支持这次后端组合对照差异，不宣称VirtIO缺陷或SDK单因；仍弱则路径未证，不自动换组合/SDK/驱动、改增益阈值或TTL。无Android/phone/云/tinycap/nativehook/新音源。本轮b2 APK字节复用；JVM/Android构建本机NOT_RUN。PR36 HOLD，global90 API26成功/API36 wake-flow完整性FAIL、test-only正控与常规workflow恢复仍待办，历史原件分母不抹除。
