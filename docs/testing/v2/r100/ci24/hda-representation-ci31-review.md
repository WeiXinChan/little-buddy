冻结供root快复核，放行前不push/CI31，不启动本机AVD/probe/音源，不构建Android。只有同一HDA单变量，SDK/b2/source7/PA参数不变。

CI30事实与参考边界

CI30 run45528773537/job138918574849，artifact14983828419 SHA522cdd7c31d535a92790bf186cd82293d430f0bd61384d8b87b0c3f286b5f7dc已由root及非作者独立核实。84host过、SDK37.3.10/build16970787/API36/x86_64/google_apis及lib/image VirtioSndCard=on文件声明过。文件默认on与emulator日志override disabled分列，不称实际运行仍on。

首错SOUNDHW_MISSING_OR_DUPLICATE是合并原因，原件没有typed计数，不能重建具体argv或断定缺失还是重复。NativeReadOnly.prepare/root/guest HDA/source7 arm/PA/波形/live全部NOT_RUN；九组16项过、JVM NOT_RUN。不是HDA不支持或低PCM，所有历史分母与CI29 host-env错误保留。

root给出的官方emu-master-dev main.cpp3519-3555中，内部QEMU args交skin_winsys_spawn_thread(...enter_qemu_main_loop,args)，不是新exec。这支持内部soundhw未必等同/proc启动argv的表示解释；参考未绑定实际16970787二进制，不当实测。本轮不新增verbose/init日志去打印全命令行。

白名单投影与两类host证据

原PrivatePulse完整私有-n双null、socket inode、同UID/祖先/真实exe、白名单PA环境与音频后端校验不减；在这些门后才读取NUL argv。只记录soundhw_count及HDA/VIRTIO/UNKNOWN/MISSING/MULTIPLE枚举，VirtioSndCard指定feature的force_off_count/force_on_count/feature_unknown_count，以及已知virtio-device冲突bool；其他参数/feature值/完整argv/env/token不输出。

- ACTUAL_SOUNDHW_HDA：唯一可见soundhw=hda，无virtio-device或feature冲突。只证明该实际参数可见。
- FRONTEND_FORCE_OFF：soundhw缺失，-feature或-feature=（包括逗号列表）中唯一-VirtioSndCard、on=0，无未知目标feature或virtio-device冲突。只证明前端请求，绝不写成观察到内部hda。
- soundhw重复/未知/virtio，force-on、重复off/on或目标feature非法表示、virtio-device冲突、两类缺证均对fixture STOP。只忽略并不记录无关feature，不放宽为“不是virtio即HDA”。

metadata-only与音源能力分离

1. SDK/lib/image文件门仍原样，identity失败STOP；基础PrivatePulse归属通过后verify_metadata_only返回BASE_METADATA_ONLY。它仍完成全部私有隔离，但不要求host HDA表示先过，所以不会再次因内部args不可见而阻断guest事实。
2. 原NativeReadOnly.prepare显式metadata_proof=MetadataPulseView，仅供只读元数据，原root一次/id0、HAL PID/UID/starttime/exe/对象/ALSA/时间预算及UNAVAILABLE不变，保存private_proof_scope=BASE_METADATA_ONLY。SDK文件门或基础隔离失败不root；基础隔离过而host表示坏时先取原受控metadata。无重复root/回退/重播。
3. 取完metadata后分别验证host请求证据和guest单一正HDA-Intel/snd_hda_intel同card；host与guest失败理由分别保留。即使host缺证也可保存真实guest事实，但status STOP/fixture NOT_RUN。
4. 只有两者全过才生成fixture_authorization=HOST_AND_GUEST_HDA。parent main同时检查status与此授权才run_arm，不能把单纯metadata AVAILABLE当放行。PA consumer显式拒绝BASE_METADATA_ONLY，拒绝发生在SDK true/任何播放之前。
5. 正常PA仍用PrivatePulse.verify的FULL_AUDIO_ISOLATION，每请求重查host两类证据；不是把metadata view交给PA。完整mic矩阵、九门、一次SDK true/零inject、必需monitor/原正文SHA/600ms零前300ms尾/8秒128000/owned回收后false不减。实际guest/live仍须CI31原件，未测不代PASS。

回归与安全执行顺序

可控回归覆盖两类合法表示及-feature/等号/CSV解析；重复、未知、force-on/off冲突、device冲突、两类缺证；基础身份/权限失败、guest非HDA；metadata-only真实代码+FakeADB可执行root一次但无fixture授权；main在metadata可用而host无证时不调用arm；metadata-only view直接交PA也在enable/play前拒绝。完整CI关键env下RequireHDA未设/0/1分别执行全suite，原旧fixture明确flag0不再受环境继承影响。没有本机实际SDK/AVD/HDA证明或新增音源；未读取完整argv/env、全maps/logcat/内存。

root放行后一次新CI31，依次文件/identity门→基础metadata→host表示与guest正HDA双门→原run_arm(7)/PA。任一未证仍STOP，无其它组合。HDA若完整/live过仅支持本次后端对照差异，不宣称VirtIO缺陷；仍弱则路径未证，不改格式/音量/阈值/TTL/SDK/驱动/属性/产品，不tinycap/phone/云。

CI28的实际VirtIO/对象SHA/弱guest/liveFAIL、CI29环境错误、CI30前置STOP均保留，BuildID/active会话未知不补造。global90 test-only正控与常规workflow恢复待办继续，global91绿色不撤销；global93空jobs不外推状态。PR36 HOLD，未证OPEN，最终验收归root。
