本轮冻结供 root live review；未获该次审查放行前不得push/触发CI27。不是普通产品设计待确认。

范围和版本锚点

实际SDK37.3.10/source.properties BuildId16970787、proto SHA9a4b0f704b0d4cdda652f89fbd50bb3d54da3d46ec8efe6e8b2a2a135ef10e69；API36镜像build13894323、ranchu HIDL7.1声明来自既有原件。b2原APK/生产source7/模型/KWS阈值/TTL/guest8秒128000采样不变。没有新Android构建、phone、云合成、adbroot、属性/HAL/effects/nativehook或格式扫描。

CI26 artifact14977967445 SHAb263da284e2bccb38718c7003e72a34d0c1c58fb85dae7f39bb31b9515e621be：隔离/READ过，SDK26次实际true、setTrue0，248包inject完成，但guest120704样本峰8、首秒后零/live进入管理FAIL；九设备门OK，后续确认/新鲜度NOT_RUN。session113是97之后默认恢复。旧失败不修改，不再归一直false或schema/permit。CI16流内SDK状态未测，不能反推为false。

参考边界

已有EmulatorService/audio_forwarder官方参考源码未与实际build16970787二进制逐字绑定。参考forwarder保存原driver/voice、切换fwd、allow_real_audio(true)，disable恢复前值，解释SDK true不等于PA消费，但不证明实际37.3.10哪行缺陷。当前参考EmulatorService文件未给出与二进制匹配的setMicrophoneState实现锚点，实际get/set到qemu_allow_real_audio及active driver关系仍UNKNOWN，不把API true当PA路由选择器。HIDL android16-release的simulate_input、300/220Hz、迟到补零/pcm_readi警告和mute0/1仅参考；simulate_input缺属性未知，不能套AIDL/default false。HAL maps/buildID/ALSA固定错误计数仍是未授权另一观测选项，本轮不执行。PA-only成功也只支持本次路径，不证明SDK单因。

安全执行顺序

1. 控制器沿原nonce/SHA/files/root/user/旧READ负控/新source7 session READ/Wire/输出门。PA helper本身按原allowlist再次核路径/hash和每fixture原采样率；enter/协议16k，两个生产提示24k，均mono S16，无重采样。
2. SDK初始化认证改为匿名getMicrophoneState必须UNAUTHENTICATED，认证getStatus/版本及初始false读回保留；PA-only全程不调用injectAudio，包括匿名空调用，无fallback/重播。
3. 原PrivatePulse完整真实归属门先过：GHA私有-n两个null、socket inode/UID、owned QEMU实际exe/祖先、白名单音频后端绑定。必须存在m06_input.monitor的QEMU source-output。失败不enable。记初始读点时间，仅一次set true并读回。
4. 构造nonce临时WAV：600ms全零前缀+原正文原停顿+300ms尾；原source SHA/frames与派生PCM SHA/frames分列。enter派生SHA固定6adff50b69642e42612c417e141e85ece88b4a03f765003cbe2fc363b0f1632a。每nonce只paplay一次到m06_input，重复nonce拒绝。
5. 必需parec只读私有m06_input.monitor，采样率与fixture同为16000/24000、mono/s16le、最多8秒且128000样本（两者先到），不改guest采样门。先核parec实际PID/source-output/格式/mute，paplay再核PID/sink-input/格式/mute。播放期间重核完整PrivatePulse，QEMU source-output必须corked严格false，否则设施硬失败停止。
6. SDK true有after-enable/during/after-playback/before-restore明确monotonic读点，不称连续全时段测量；任何读false失败，不重新开或重播。paplay/parec超期、错route、监听失败或异常全部硬失败，保固定PaFailure白名单reason和项目栈，不导出原始stderr/完整env/command/token。
7. finally先有界回收paplay/parec、join reader及原metadata观察线程，再set false并实读。主错保留、清理错误附注。临时payload删除，严格合成monitor原始旁路按nonce/hash作为本次原件导出，CI临时工作副本随runner清理；无环境/儿童内容。
8. owned回收/false读回后验证monitor整段原正文（不是局部片段）波形相关性，相关门.98仅用于host完整性，不改KWS阈值；保source原样本全覆盖/lag/实际monitor frames/hash。host完整不代guest保真。receipt校验派生hash、nonce、source SHA、所有前置/资源门。只有全部满足才写原completed握手。
9. 原完整mic断言和其余九门全部保留。enter失败则后续NOT_RUN；过则继续原提示完成watermark/旧buffer/旧decode/自提示/新确认/零上传矩阵。不构建新Android包，JVM本轮NOT_RUN，精确fetch b2及全树守门保持。

本机证据边界

真实Ubuntu24.04 Pulse16.1 private-n两个null；真实paplay/parec/完整helper/整段16k与24k正文。SDK控制为fake，metadata client实际PID/UID/socket/env均实核，但exe身份仅测试mock为QEMU；不会把该模拟当GHA动态身份PASS。测试client只在fake SDK true时uncork到私有合成monitor，false时cork，不接真实hostmic。所有owned进程/线程退出，临时server目录清理。真实GHA/guest/live仍待获准后的CI27。

本机完整否定回归包含错误私有监听、SDK false、播放超时、monitor错误、恢复失败；另host单测覆盖错route/采样格式/mute/PID、原格式和SHA、完整正文截断、隔离拒绝不enable、不inject认证正反控、先停资源再false、主错不被恢复错覆盖、重复nonce不重播、enter派生hash不能篡改。冻结后附准确计数和实测JSON，不把源码/host green当产品验收。
