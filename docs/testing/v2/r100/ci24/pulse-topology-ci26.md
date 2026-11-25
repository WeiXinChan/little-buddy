CI26 host-only全拓扑schema修复，PR36 HOLD。

CI25 source7/session97 READ/gates通过，模块schema修复已越过；首次注入前NON_MONITOR_SOURCE，0包/setTrue0，无RPC，SDK false恢复、资源清理通过。原artifact14977590630 SHA256 6e3c93de2246f5cf55828bc125696c50c6d2e0bed90f6755b933105f7653818f保留。不是弱PCM/SDK gate无效，校准NOT_RUN；CI24两个不同前置失败亦保留。

实际Ubuntu24.04 Pulse/pactl16.1两个null源：source.monitor_source是sink NAME，而sink.monitor_source是source NAME。source/sink name必须唯一且双向严格匹配、driver必须module-null-sink.c、owner_module必须同一null模块且两个sink分属不同模块；模块仍只允许native-unix及两个null。缺失/冲突/跨owner/额外物理源/错误driver/重复index/未归属client/错误source-output均拒绝。失败保固定隔离reason和白名单投影及项目栈，未知字符串不原样写入。

本机真实私有-n Pulse完整verify已经执行：真实bounded bytes→sources/sinks/modules简表/clients/source-outputs→整图，真实UID、祖先、socket inode/PID、/proc音频环境白名单校验。元数据测试client用真实libpulse START_CORKED流，永不uncork/read，不播放/采集音频。为运行完整函数，仅该测试Python client的/proc/exe解析显式mock为qemu-system-x86_64；未mock时确认QEMU_EXECUTABLE拒绝。它不证明GHA实际QEMU可执行文件/环境，本机无真实QEMU输入实验，生产未添加豁免。owned client与Pulse均正常停止/等待，临时目录清理。所附复现脚本明确此测试边界。

CI25现成GHA clients白名单：index1 PID3290 binary qemu-system-x86_64，index2 PID3814 binary pactl；source-output index0 client字符串1、source数字1、corked=true。实际字段与PID路径解析相容；实际/proc身份/环境仍由CI26原硬门核，不凭metadata属性信任身份。repo fixture是本机完整实际查询的白名单投影，保留真实字段类型/关联；不含arguments/完整properties/环境或PCM。

43项host测试通过；另有实际本机完整verify实跑证据。复用b2 APK，无Android构建/JVM新执行/source6/TTL/阈值/音量变更，原设备门全保留。单次CI26实际SDK/guest/live/确认新鲜度仍待原件，不能用本机schema通过替代。
