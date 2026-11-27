# 正常会话TTL与技术失败分流

基线main `7c2bd15aab247509fc9c5c13cc5f3cae79098d54`，后端等价已部署8a360e3e。只改V2 Session/VoicePeer，不触V1、供应商、Android或运行配置。零真实ASR/model/TTS/image调用，未部署/安装。

## 已证与未证

code28现有三个只读报告显示：同PID录音running两点；随后AppOps停止，上一录音时长9m58.350s；11条终态从TECHNICAL OTHER_ERROR/HOLD到native release/worker joined，缺clock/source。不能把时间接近10分钟当作已确认设备根因。

原文件不改，SHA256分别为：current-status a62ce2c8ccb8f27894f0f13a8764d44ece42880cc768db07c5b10694b0c4178f；recording-counters 381d61a0339f198aa315820e5c7446c9bfb622937bc81595bcb4823e1438d943；terminal-events 3a9da2759386fe4c5ab02480deb66f722656e7bf012f95bb320fee9de1c35594。

独立fake-clock反例已证：实际Session持续合法heartbeat但无confirmed interaction，不续600s保留期，600.01秒时实际monitor输出revoke+failure timeout。原失败日志保留。这是明确代码路径缺陷，尚不是code28现场归因闭环。已有valid_interaction仍按原契约更新TTL；本修复不延长TTL、lease、response/progress或input budget。

## 最小修复

Session在_live清空前锁定失效来源。先比较当前有效response/progress期限、heartbeat与TTL；旧response_expired、较早或同刻技术期限不归类正常TTL。管理暂停的TTL到期单列management_expired，保留管理/技术失效路径。monitor原input-budget失败分支仍优先fail closed。

只有session_expired进入正常收尾：捕获Session对象、epoch/revision/connection/turn/output，保留原scope；先清会话/缓冲/代际状态、撤销播放、确认generation/recognition及动态retired退出，随后发正常结束。每个await后核对原scope，不借新Session、epoch或generation。通知按已死Session幂等。关闭任务只等待确认，不以cancel当释放；未确认仍quarantine+技术voice失败，保留句柄。原resource .5s退出预算未改；沿既有generation/recognition各自有限取消，并对retired做.5s有限观察。

run中heartbeat/scope可能先于monitor发现TTL，改为等待同一个monitor完成该终态再退出；显式clear/end不等待TTL通知。取消时新Session替换后旧monitor继续监控新Session，不能清掉新会话或发送旧通知。

## 给Android的固定契约（待其作者接入）

```json
{"v":2,"type":"session_end","epoch":0,"reason":"session_expired","session":"<captured-old-session>","turn":0,"revision":0}
```

字段结构复用conversation_ended；epoch/session/turn/revision均取被关闭的原scope，不能由终态帧学习新身份。当前VoiceClient.kt只接受reason=conversation_ended，**尚不接受新reason**。Android配套应在同一imageScopeCurrent(event)校验下显式准入session_expired，沿现有close/sessionEnded回调释放并回等待新唤醒；其余reason/旧scope必须拒绝。childBlocked管理门禁不放宽；管理过期保持既有management_state expired/技术处理。后端错误、lease/input/reply超时、安全local_help及设备凭据expires_at的1008关闭均不改成正常TTL。本PR不声称客户端已完成或真机已修好。

## 定向证据

55方法PASS：新15个生命周期方法+既有Session/management/stop-idle。包括：

- 600秒合法heartbeat空闲的正常通知、TTL/lease/预算不续期；单poll跨response/progress与TTL、heartbeat更早/同刻、已expired回复均保留timeout；仍有效reply/ingress场景不续原边界。
- management expiry与安全拒绝分层；实际run中heartbeat先发现TTL的正常退出，显式clear不伪装TTL。
- pending generation/recognition取消及晚注册close任务确认；未确认retired仍保留+隔离；重复通知幂等。
- 清理中的Session/epoch/revision/connection/turn/output和generation替换不发旧通知；实际run替换Session后保持新会话活跃。

这些是零供应商实际VoicePeer/Session的工程生命周期证据，不代表声学/真实设备已验收。不跑全集650、不新长测。root审合及Android对齐后再部署/安装与有限现场验证。
