## 现场与结论边界

PID30942（code38、activity1/transport0，语音客户端capture0、物理capture1）和 PID32321 的后续合成唤醒、新窗口 QualityFault 是不同记录，不拼统计。

Mac补充的30942手机MONO毫秒：wake=228245641；rev12 first_audio=228267112、native head=228267155（wake后21514ms）；rev16 endpoint/seal=228278847/228278855，bound/track=228279123/228279182，该revision没有观察到首音或head；最后可见rev24 probe=228288850；failure(timeout)=228291504。故 wake→failure=45863ms、最后probe→failure=2654ms。rev6/12/16均观察到客户端seal发送，不能沿用“没有seal”的早期摘要。客户端发送不证明服务端接收；没有独立 endpoint accepted/completion 或更晚输入证明。

captured_last_speech_boot_ms=228288550 是BOOT域，日志MONO由System.nanoTime生成；本报告不直接将BOOT与MONO相减，也不跨主机相减。旧observer窗口过期无行不能证明无故障；root已重启开新窗口。本次未重启、部署或调用供应商。

**PID30942现场来源仍UNKNOWN**：源码/离线证据发现与摘要相容的两个真实缺陷，但缺该次服务端分支/预算快照，不能把候选宣布为现场根因。新窗口 `safety/QualityFault peer1 turn5 epoch26 revision64 elapsed234473` 尚需匹配客户端进程与scope，不能据此解释旧30942。

## 已证实并修复

1. 旧输出的budget误杀新输入。advance只暂停旧播放，保留noise/backchannel恢复可能；但monitor仍poll旧输出deadline，即使新revision已有真实speech、自己的15s尚未耗尽，也会发timeout关闭整个会话。离线原代码实测：旧输出deadline125，新speech/probe在122.346、当前deadline137.346，125即SERVER_TIMEOUT。

   新增精确output owner（Session对象/connection/turn/epoch/revision），在原旧deadline/60s progress实际过期时才撤销旧输出。仅当更新revision有真实输入/已seal文本、当前预算有效或原THINKING暂停、会话心跳/TTL有效时执行。旧输出不延长、不再可恢复；不造ACK、不提交未播放内容、不清当前capture/analysis、不新开供应商任务。沿用一次0.5s取消，监控器与stop同时退休同一任务也共享同一绝对deadline、只cancel一次，不得续时/二次cancel假装退出；资源不配合即quarantine且不给恢复资格。await后重验session/connection/turn/epoch/revision/private/output/budget对象及anchor；新revision到来不覆盖它。当前15s、THINKING例外、TTL/heartbeat、容量与retry预算均不变。当前输入真正过期仍timeout；未过期的旧输出仍可按原noise路径恢复。

2. 旧输出异步异常借用了新revision。Operation的输出工作允许revision=None以保留暂停/恢复，但异常分支因此可在新input到来后撤销资源并发failure。原代码受控旧TTS TimeoutError实测向新revision发送timeout。现在捕获response revision于respond调用时，在异常副作用前和commands await后均验证revision；旧异常不发布给新输入。

3. 当前普通生成失败缺恢复scope。原 `_respond` 非安全失败只有code/epoch；code35+的真实VoiceClient要求session/turn/revision与已建立scope一致才能授予已有SERVER_VOICE有界恢复。缺字段进入协议失败/永久HOLD，而已有回归的手写服务端总补齐scope，未覆盖生产后端。

   现在仅当前、非quarantine且fact prefetch关闭已确认的响应失败带精确原session/turn/revision；prefetch不配合关闭仍隔离，不借恢复scope掩盖未退出任务。QualityFault仍拒绝输出且零TTS，不降审核、不改为成功。使用既有客户端流程：先确认旧native释放，进入本地等待新自然唤醒，只有新wake才建立一次新连接，不重放失败请求。quota/auth/timeout/safety/unknown及quarantine没有因此得到SERVER_VOICE资格；不把所有timeout改为自动重连。

## 验证

`tests/v2/test_superseded_output.py` 使用真实 VoicePeer.run/JSON输入/ACK、受控ASR/endpoint/TTS与时钟；stream ASR OFF/ON都覆盖：旧timeout异常不污染新rev、新输入有效时旧budget只淘汰旧输出、当前原budget仍过期、旧ACK不提交、不合作cleanup/prefetch quarantine、新revision发生在cleanup期间仍保留其capture/budget、旧60s进度过期只淘汰旧输出、worker尚未启动时仍绑定原响应revision、并发stop不续0.5s、当前QualityFault零音频且scope精确。原错误测试先FAIL，修复后PASS；不是复制monitor实现。

`test-v2-recovery-tls.py` 新增 production_quality：生产VoicePeer+UnifiedProviders审核拒绝，经真实VoiceClient/Capture/RecoveryEpisode/Handoff/Playback与localhost TLS，确认旧释放→新wake一次连接→完整FIFO导入→新回复/native head/ACK。该次明确选取code38 `bad1a0a2` 的原始VoiceClient源码（RECOVERY_VOICECLIENT_SOURCE）；其failure解析/恢复资格与后端分支版本逐字一致，仅expiry状态增加有差异。其余生产Capture等从后端分支编译，Android/native/KWS端口为受控JVM替身，不证明真机效果。另以unscoped精确旧wire envelope作负对照，确认协议失败、零新连接；原quota/auth/timeout/safety/unknown/stale_scope/slow等拒绝边界保留。Activity界面状态仍需root真机验证，未将JVM owner driver称为真实Activity。

复现（仓库根目录，已有匹配编译依赖，串行2GB锁）：

```sh
scripts/with-build-lock python3 -B scripts/test-v2-superseded-baseline.py
scripts/with-build-lock python3 -B -m unittest tests.v2.test_superseded_output tests.v2.test_timeout_boundaries
git show bad1a0a2c454a24759d81f34dabb4f2c21e1a645:app/src/main/java/com/littlebuddy/v2/VoiceClient.kt > ../code38-VoiceClient.kt
scripts/with-build-lock env RECOVERY_VOICECLIENT_SOURCE="$PWD/../code38-VoiceClient.kt" ANDROID_JAR=<已有android.jar> UNKNOWN_INPUT_CLASSES=<匹配V2编译类目录> python3 -B scripts/test-v2-recovery-tls.py
```

不重新生成提示音、不改APK/model/wire contract或开新agent。root审核PR/CI后按原后端打包验证/私有激活流程发布；原参数与Qwen3.8配置保持。真机只由root协调新预算：同一新观察窗口匹配服务端scope和客户端过程；不将32321的未复现代替30942。回滚source即可，无状态迁移。旧code33第二SERVERVOICE也仍OPEN UNKNOWN。
