本批是一次有界诊断候选，不是TIMESTAMP_STALE根因修复或语音验收通过。基线main8a360e3；仅Android诊断与退休回调门禁、code24版本及相应离线检查，不改backend。用户USB就绪但作者不操作Mac/手机，由root审后一次自动覆盖安装和短采集；不要求用户分项复现。

已读既有服务器三份脱敏报告setup-report/failure-timeline/resume。首因顺序为PROTOCOL_FAILED@152224922，124ms后TIMESTAMP_STALE@152225046；flow2 BEGIN@152225202、CAPTURE_READ READY@152227284。观察1/1有故障，第二路READY不能冲销。root13:55服务重启是后来的独立事件，不拿它解释此前首失败。

来源核对从原交付identity/实际APK SHA/嵌入inventory定位：fix8 source7a79c7b/APK97a0fac3，b568/APK94dccee1；NativeReadLedger、CaptureMonotonic、CaptureClockEnvelope/Failure、Capture/Bootstrap/Uploads、RecorderLease、ManagementCapture、VoiceClient、WakeReader/SpeechDetector、AndroidPinDiagnostic共13文件逐字一致；host的startChildCapture/releaseAudio也逐字一致。故91.46秒旧观察与62.43秒新观察不是已证集成回归或设备时钟根因。原报告、失败和候选不覆盖。

确切判据与本次数据：
- mono=System.nanoTime()/1e6，getTimestamp使用TIMEBASE_MONOTONIC。boot桥elapsedRealtime包含深睡，差值>5ms另报TIMEBASE_CHANGED；本次bridge0不能推出无其他调度问题。
- NativeReadLedger.refresh在API后重新采时；runtime phase2ms。age判据为 `(mono_after_ms+1)*1e6-(stamp_ns-2e6)<=100e6`。报告raw age134042312ns对应保守137042312ns，应拒绝；100ms等值通过，超1ns拒绝。
- check_gap35ms是上次检查到API前，api113ms是本次调用跨度，合计148ms；同一个返样本相对API起点约21.042312ms不是“已在起点观测到新stamp”。不能把API延迟刷新成采样时间，也不能因原生buffer尚有room而忽略age。
- `df320/dn19772539`是相邻对，不是长窗口率。先前LONG_RAW_REJECT_PHASE_FEASIBLE仅说明旧raw oracle与有限phase模型不同，不是新终止故障。
- 旧age字段使用attempted或cached observed，getTimestamp非成功被适配成null，旧报告缺return code/candidate-present/scope，因此不能区分硬件旧pair、API延迟、关闭中晚返或缓存观察；并非已证硬件永久不支持。

[官方AudioRecord](https://developer.android.com/reference/android/media/AudioRecord#getTimestamp(android.media.AudioTimestamp,%20int))说明可用时返回SUCCESS，否则可返回ERROR_INVALID_OPERATION；[AudioTimestamp](https://developer.android.com/reference/android/media/AudioTimestamp#nanoTime)称capture time为估计值；[SystemClock](https://developer.android.com/reference/android/os/SystemClock)说明mono/boot对深睡的差别。官方语义不保证本工程的2ms相位精度或100ms新鲜度，现有有限假设/保护全部保留。

最小改动：
1. 原fail(code)把playback/lifecycle/route/backpressure/management/expired等压成PROTOCOL_FAILED。新增RUNTIME_CLIENT_FAIL固定FailSource，receive错误另带固定WireKind/WirePoint；无原始kind/报文/异常message或动态类名。CLIENT_CLOSE_BEGIN/END确定关闭是否卡在本地清理。
2. process-local activity/transport/capture代际固定到创建对象；时钟详情和LONG_PAIR绑定同一不可变scope，不从当前global flow临时借新标签。Activity CREATE/RESUME/PAUSE/FOCUS/NEW_INTENT只记录固定阶段、是否MAIN、CREATE时是否savedInstanceState；不读Intent正文/extra。
3. Capture取消/stop begin/end/native release/worker joined及失败均带旧scope。native read/TIMESTAMP/KWS/CLEANUP为固定operation，在cancel时可区分在途JNI；API前后复用ledger已有采时，result为SUCCESS/UNAVAILABLE/OTHER/IN_FLIGHT等固定枚举，补stamp_ns、是否返回、phase/保守age/上限/starting，不改变时钟判据/计数。
4. 确定的局部缺口：owner检查之后到UI执行之间可换管理页或recorder，旧UI只比transport。UI现取最新transport/capture/lifecycle/client判定，retired只记FAILURE_UI_RETIRED，不借新页或新recorder触发HOLD；当前真实故障仍HOLD。纯门禁队列反例覆盖旧谓词会接受/新门禁拒绝，但不冒称这就是本次OPPO路径。实际Capture受控timestamp期间取消的反例保留typed stale/旧scope、无失败投递/PCM。

诊断仍只V2诊断构建显式开启；同V2PinInitDiag标签、共享256行/15分钟、独立非阻塞写线程。状态是近邻采样，不是跨线程原子快照；native_released/worker_joined代表确认值，非JNI可中断保证。clock缺context时显式ctx_known=false/-1，不伪造新代际。runtime字段按stage只打印该stage已采样的值，不让无关默认false冒充观察。无音频/转写/正文/端点/PIN/token/nonce/签名材料/安装ID；公钥/私钥不导出。

候选code24/2.0.0-rc9.diagnostic1.integrated1.device1，appId/既有7705签名及已存PIN/连接/Keystore alias不变。私有preset仍由本地忽略输入生成，不能提交或上传APK普通附件；目录0700/文件0600。本批仅一次候选，源固定后再build；不因本地绿就称硬件修好。

离线边界：实际ledger重放113/35/134数值、保留100ms边界/NULL缓存不续预算、诊断sink异常隔离、当前故障仍应用/旧代际与失焦不应用；实际Capture受控native返回晚帧+取消不投递失败/PCM；既有时钟漂移/读积压/初始化/清零/21/50帧与Sherpa受控回归。未执行设备/声学/云/长测。新增字段只能供root自动短采集定位，不要求用户输入PIN或重配。

root采集建议：保留系统PID与设备单调时间，固定V2PinInitDiag tag所有行；记录安装自动启动、额外am start是否发生及其时间（若已有自动启动，不盲目再启动），不要把多实例/焦点/退休路日志当作同一路硬件故障。可参考 `adb logcat -v monotonic -s V2PinInitDiag:I '*:S'`；仅root/Mac获授权执行，作者不执行。记录首个RUNTIME_CLIENT_FAIL.source、同scope CLOSE/CANCEL/STOP、clock api_before/after/stamp、FAILURE_UI_APPLY/RETIRED及新scope起点。对当前scope真正超期继续安全停止；不抬年龄/phase/buffer/rate、无无限重连、无未唤醒上传。
