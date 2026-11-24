协议原稿及审定后实现记录；接管方已批准方向进入实现，代码/真实设备仍待非作者验收。A27/F01保持OPEN。

现有有限KWS只提供命中与声学时间，不能由静音判断否定续句/独立意图。历史75测试、45+4场景、原WAV/哈希/失败XML全部保留；旧四条预期记oracle争议，不改绿。

状态：CLEAR（无未决否定）、UNCERTAIN（否定/引用/续句边界未消解）、CONFIRM（已提出一次本地退出确认）、EXITED。管理身份仍未验证，任何状态不授予设置写权限，所有管理音频留本地不上传。

CLEAR中完整、边界清楚的“取消”或“退出管理页面”直接退出到WAKE，不续旧播放/云会话。识别否定、讨论/不完整词或不确定上下文转UNCERTAIN；不凭3.5秒静音恢复CLEAR。UNCERTAIN收到退出候选仅进入CONFIRM，保持管理并给一次本地提示“要退出吗？请说确认退出，或点取消按钮。”一次不确定交互至多提示一次，不循环催促。

CONFIRM只接受完整独立“确认退出”退出；“继续管理”、再次否定、讨论或识别不确定均保持管理，回UNCERTAIN，不再重复提示。确认期限建议8秒，仅使确认失效，不使旧退出自动执行；新完整确认需重新建立候选。按钮“取消”始终明确退出，不依赖语音。长期不确定不永久吞新请求：新完整退出请求可重新打开一次确认窗口；这是有界确认能力，不假称理解主观意图。清楚普通退出在CLEAR不多一道确认。

识别适配：沿现有管理专用Sherpa paths8、score1.5/threshold.25/trailing2，新增“确认退出/继续管理”的词表音素须先同版模型实测。确认词前后否定、引用和额外语音保守拒绝；仅关键词命中不足确认，须与生产边界及同一管理generation/确认nonce匹配。无需新增模型/ASR/云调用。提示用本地固定文本/可用离线提示，不新增付费或真人音源；本地提示声不得被输入当确认。

代际：进入管理、退出、HOME/失焦、换人销毁确认nonce与候选；迟到结果不能退出新管理期。超时只撤确认，不复播/上传。识别失败可使用现有按钮，不能把自称家长视为认证。

评审门：先审状态和措辞/识别适配，再实施。版本化物理时间用例至少包括：CLEAR普通退出正例；否定后2.3/3.8/4.7/6.2秒续说均不直接退出；UNCERTAIN重发完整退出→一次确认→确认退出；否定/引用确认词；确认超时/迟到/换代；噪音和语速音量变体；按钮出口。实际VAD起止、KWS绝对样本及状态事件一同记录。历史长停顿oracle不删除，另列协议v2期望及独立审查结论；最终AudioRecord→Capture→owner验，不以离线回放代替。

接管方非作者已核本提案原SHA256 0ef2b341de53335699a0341a35b8576cbce6e972416044dea3ed410ae7dbdf28，批准方向进入实现，不是产品验收。落实补充：8秒期限采用elapsedRealtime固定issued墙钟，arm不延期；实际draw后回执，再取得MONOTONIC原生AudioRecord timestamp且其时间不早于回执，以native framePosition而非processed samples设确认起点。旧缓冲/特征中起点不越过此门槛的确认拒绝；无有效原生timestamp保守保持管理。音频帧为16k单声道，采集句柄不重启计数；额外sample期限为保守上限，不替代墙钟。参考Android AudioRecord.getTimestamp官方：https://developer.android.com/reference/android/media/AudioRecord#getTimestamp(android.media.AudioTimestamp,int) 。本地文本提示不产生可自识别的播放音频。UI/owner停顿、8秒无PCM、旧确认和确认后新输入须分层回归；原生缓冲阻塞配对尚待设备实证，不将纯状态测试当完整证明。

本轮实现验证：原墙钟反例在无PCM推进8.1秒后错误退出已复现并保存；改用issued固定elapsedRealtime截止（arm不延期）后用可控时钟回归。当前12条同版原生KWS/PCM→生产边界v2回放含正常退出/确认/继续、不要/别/不确认、引用确认、否定/引用继续、旧原生watermark之前的确认拒绝；8条状态测试覆盖nonce/代际/重复/期限/未知timestamp。实际Native timestamp及“提示前已解码命中暂停→新提示draw→释放旧结果不退出→新声音确认”的AudioRecord测试已接线，动态通过与否由CI原始结果决定。短否定单字词不足曾导致不确认退出误通过，补完整本地短否定词组后回放通过；不降低score/threshold。6条静态TTS已用满，来源/哈希及两条DSP组合来源独立记录，不再新增云调用。

已审三项接续（v2.1，待非作者最终动态复核）：连接意图由owner持有generation/requestId，取消旧voice后清引用；没有3秒丢弃或反复cancel轮询，真实released/workerDone/lease归还后的完成事件只消费仍有效的一次意图。HOME/失焦/新请求撤销旧意图，迟到旧stop不得抹去较新request，资源故障隔离不复活。循环保留两份KWS模型，仅同worker安全替换stream清特征，resetAt保绝对坐标；普通唤醒尾部坐标保持，原生reset测试已接线待设备证明。

管理提示改为可听24kHz单声道本地静态CosyVoice。现有本地资产无语义匹配提示，授权生产短提示一次生成2条：确认提示3.82秒、留在管理1.94秒；参数/hash/用途见assets/management/provenance.json，不扩测试采样。独立本地Playback需native head到总帧且stop/release成功、非静音且路由有效才成功，随后200ms保护；此保护不是OPPO声学效果证明。整个提示期间采集只读并隔离，不喂KWS，完成后清stream特征并取结束后原生watermark。失败保守停留，按钮始终可退出。

v2.1期限：UNCERTAIN退出请求先进入PREPARING，独立6秒有界准备，确认接收关闭。仅当前nonce/generation的真实播放完成并结束保护的回执可一次发布CONFIRM，使用回执时刻固定+8秒；worker延后消费不能延长。arm/重复完成不能续期，准备超期、旧提示、失焦或取消不能发布。原“请求时刻起8秒”版本历史保留，因实长3.82秒提示的端到端余量而明确分阶段，不把同一窗口任意扩大。PREPARING完成接线断言、317ms迟到disposal、静音/失路由/超时输出、旧请求撤销均有确定性回归；真实READ、提示自身反馈/新声音确认及HOME释放待新CI，不以状态测试替代。

CI子进程清理也有界：只针对本次启动emulator/Pulse PID，adb emulator-5554终止有8秒上限，TERM/KILL各有期限，仍存活则记录cleanup错误且不阻塞无限wait。仅工作流/文档改变不重建已匹配app树制品。
