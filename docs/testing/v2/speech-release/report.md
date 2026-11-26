## V2专用语音连接释放修复

基线9fc7d4ad93f5a8b256f911748981bede53ce53a5。root真实FAIL原件逐字保留：40帧/40ACK，synthesize退出500.95ms取消/WireError，game未提交；不是ACK问题。此前两次真实失败、诊断与旧QA失败不覆盖。本批0供应商云调用/未读真实secret/config/未部署/设备/合并，不重建APK。

生产仅新增backend/v2/speech.py并接runtime.providers；V2Speech继承共用DashScope的业务协议/TTS/ASR，但仅重写V2 speech_socket生命周期。backend/dashscope.py、VoicePeer、Session、帧4800和外层0.5s均未改。模型仍qwen4-max；没有改提示词、审核、重试或付费路由。

### 锁定API与确认语义

锁定及实测安装websockets==17.4，已读本机库实际源码，api-evidence.json记录方法模块/行号/源码hash：Connection.close通过send_context发送Close并等connection_lost；send_context超时调用transport.abort，再等待connection_lost_waiter；wait_closed对该waiter使用shield；connection_lost才将waiter置为完成并取消keepalive、关闭接收队列。connect默认上下文退出等同connection.__aexit__。不能仅以发送Close/取消Task/调用abort作为释放证明。

新V2 socket配置close_timeout=.15（保留open_timeout3、proxy=None、认证headers、max_queue4/max_size128000）。退出由适配器拥有，不再调用默认connect context退出：创建close和wait_closed任务、捕获库keepalive；给正常close最多.2s观察，未关闭或取消时显式abort；共享总.35s deadline内观察close/wait_closed/keepalive都终止，并确认connection_lost_waiter完成且未被取消、wait_closed/close成功才返回。不是调大VoicePeer的.5s；预留约.15s调度余量，实际环境仍需root有限复验。

取消期间仍先中止/确认，确认后重新抛CancelledError，不吞正文取消或异常。若确认失败：固定SpeechReleaseError、标记release_failed、保留release_tasks句柄并拒绝此V2 adapter后续连接，未完成任务取消但不将取消当释放。外层已有resource隔离逻辑照常工作。局部release_tasks只含任务句柄，last_release仅固定元数据；不输出供应商异常正文。无法物理中断任意stubborn实现/卡死事件循环；未确认需调用方已有worker/连接隔离，不承诺硬实时或无残留。

### 实际本地检查

新增8方法：

- 真实loopback WebSocket正常握手关闭，确认connection_lost/任务结束。
- 原生TCP升级为WebSocket但不读/不回应Close，客户端短超时后实际中止，确认connection_lost，<.5s。
- 真实未回应关闭进行中取消：实际abort、所有任务终止后抛取消。
- 真实连接正文取消及正文异常均保留原异常并确认释放。
- 合成connection_lost永不确认、close吞取消：.35s观察后failclosed且保留pending，拒绝后续连接；fixture显式释放并回收，不声称物理关闭成功。
- 实际VoicePeer＋UnifiedProviders＋本地DashScope协议socket，3轮每轮2句，6次真实本地TTS socket；每句9600字节合成PCM依生产rechunk，4帧/4ACK每轮，三轮全部最终game提交，所有资源退出确认。
- runtime真实工厂读取临时合成600凭据选中V2Speech，模型同样持有该实例；V1方法保持原实现。

local.log为最终8PASS；affected.log为较早7新增＋safety_help/M05的39PASS；harness25.log为25PASS。去重合计8+32+25=65个方法PASS/0FAIL/0SKIP（非相加重复日志）；编译/diff通过。safety_help集合包含原显式负控检测方法，不当作新增云或有效音频证明。仅localhost真实WebSocket，模型/音频内容合成；不是供应商TLS、ASR、声学、手机或真实多轮玩法质量/P12/P15通过。

### 交接

root独立QA后，使用原有限单例监督driver与真实配置进行一次必要复验。无需变更image配置/模型/协议/Android/0.5s预算。预期synthesize exit confirmed并低于0.5s、正常多句最终state ACK；真实关闭不确定仍隔离。该复验由root决定，本批不发云请求，不追加自动重试。
