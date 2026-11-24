global82 TLS夹具与CI20合成输入时序取证

TLS仅改JVM夹具：真实后端/TLS/OkHttp/socket和容量4负控保留。segment1.end建立ACK_PENDING，第5个未消费frame进入push前记录confirmed=false并发布latch，独立线程沿同socket发真实ACK。>4、legacy assertFalse及IllegalStateException、SegmentBuffer成功断言保留。首个错误/真实ACK为终态，错误后迟到回调不复活失败流；不是注入confirmed。计数于第5帧冻结，ACK/socket线程有界清理。

服务端每段第5帧前延迟0/500ms × ACK延迟0/200ms，共4调度、各legacy/SegmentBuffer配对。原10秒await/4秒容量等待不变。Debug与V2Debug针对性JVM/TLS各1项通过，各含8真实连接；所有legacy先容量错误且confirmed=false，正控真实ACK_RECEIVED。服务500ms延迟由实际ACK_PENDING→第5帧≥500ms断言约束。首轮中间结果虽绿但终态后confirmed被迟到ACK改写，XML保留，不作最终证据。

global82 API26原120项1失败1跳过、第168行失败保留。该run GitHub artifacts为空，未取得旧失败XML；原job138759692809失败日志摘录及本机修改前XML保留，不伪称旧期望通过。不删/ignore任何测试。

CI20 artifact14964637661 SHA256 2a3eb90870e8f4f33456fc6bbd7e014ca86d512f5e2b67a7c542a5ea7005edf3已核。mapped环回/ownedPID、匿名拒绝、Bearer37.3.10.0、hostmic=false和RPC218包已过，live管理仍失败。guest106112样本/6.632秒短促弱信号不能称全零、认证失败或已证格式/速度根因。源同模型进入管理、capture无hit；提示配对仍NOT_RUN。

本机用实际SDK37.3.10 proto生成类回放当前packet_plan：16k/Mono(0)/S16(1)/MODE_UNSPECIFIED(0)，218包、首包640字节，反序列化拼接与64960源样本+300ms尾零逐字节相同。只排除本回放序列化/枚举错误，不证明SDK原生消费。官方主干AudioStream/audio-capturer/audio_forwarder仅参考，非已证SDK同revision；hostmic=false不等于gRPC静音。

新增动态证据，暂不改ready/arm：请求含guest elapsedRealtime/System.nanoTime和native session/read frame；探针仍8秒/128000样本，最多34个250ms读取水位并记首次越界/冻结时钟。这是生产read完成水位，不是硬件采集时间戳。host同nonce持久化pwd/readlink/test/hash、首包和注入阶段，前后adb /proc/uptime以host前后时钟括住guest boottime，含10ms量化；不直接相减两机单调钟。guest记录12秒完成/enter await起止及首异常。原nonce/SHA/固定fixture/专用AVD隔离不变。诊断本身adb延迟也纳入新数据，不倒推CI20旧时序已证。

产品源码/主APK不变，仅构建受影响AndroidTest包。原工作流完整门照跑，用新数据判断输入与采集/断言窗口是否重叠；未测不称修复，不扩大授权或await、不降阈值、不绕生产Capture。PR36 HOLD，未证项OPEN。

官方参考：https://android.googlesource.com/platform/external/qemu/+/refs/heads/emu-main-dev/android/android-grpc/services/emulator-controller/server/src/android/emulation/control/audio/AudioStream.cpp 及同主干android-qemu2-glue/audio-capturer.cpp、audio/audio_forwarder.c。
