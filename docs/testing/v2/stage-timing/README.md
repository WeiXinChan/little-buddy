# 一轮V2非内容关联计时

基线main af46e0c3867f08f9ab7fc8735610123009bca807；后端与在服0329097等价。只增加opt-in诊断，不并行化供应商/审核、不修改ASR/模型/TTS、15s输入预算、.5s释放、租约/TTL、安全或Android。

`with backend.v2.timing.observe(Trace())`覆盖**一轮表达**。ContextVar传递到本轮并行tasks，记录固定enum、monotonic相对ms、临时round=1、epoch/revision/turn整数、count/bytes、固定outcome；不存Session ID、内容、PCM、URL、密钥或异常message。首次有效记录pin peer/Session对象/session_id/connection，只输出整数scope；新Session/connection不借用旧trace，合法stop→open/bind可改变turn/epoch。结束后继承该context的旧任务也不能写。observer只支持同步函数，传脱离只读row；抛错后禁用该observer，标observer_failed，无打印/语音异常；不保证任意第三方callback耗时或副作用安全。每轮最多128条，超过明确truncated，不是连续完整峰值。

默认不创建Trace、不生成record、不安装共享provider observer、不写log。ASR/TTS资源enter成功分别为asr_ready/tts_ready；它们不是额外供应商时钟。tts_connected/task_ready是显式V2 resource作用域里转接已有共享供应商mark的新观测，不导入V1历史记录。asr_final为finish返回，asr_released为生产owned_resource完整退出。ack_received仅收到；ack_progress在Session.ack返回成功且head增加后记，effective_ack仅response_confirmed由false变true；模拟ACK不证明speaker。

`python3 scripts/v2_stage_probe.py`默认disabled。显式执行必须固定clean HEAD、--source完整SHA、全新--output目录、项目with-build-lock对应2GB监督cgroup。工具仅一轮、仅一次probe、真实loopback临时TLS/生产VoicePeer+Session，合成client按16k上传/24k输出节拍模拟ACK，无手机。使用已有私有路径配置/凭据，不复制；固定模型1017/fun-asr/cosyvoice，HTTP client与production相同，无fallback。

fixture仅接受约定AIFF SHA1b7d418ac0550d7cb4e9a6f5c947bf72825caa464b616d6279c678dd3ab3aaad及metadata：22050Hz/68097samples/本地Tingting regenerated。一次ffmpeg转换内存s16le16000，输出实际samples/hash，不按文件bytes假算；转写仅判断空/与固定case一致布尔，不输出实际转写。若不符直接停止，不继续把它作为相同请求性能。fixture/PCM/私有配置不入Git。

所有实际provider发出前统一扣数：ASR1、text9，endpoint/plan/facts各最多2、review最多5；生产原共享一次retry/repair仍决定是否可调用，工具不重试。首供应商失败关闭meter；原生产若尝试再读也会在I/O前被挡。TTS4；compact不获额外预算、图片生成/复审/下载均在边界拒绝，bind不宣告图片能力。普通介绍初始空Session。意外需compact时预算不足终态，不删除真实compact逻辑。

45s轮/55s父，原15s表达预算和.5s退出边界不变。父只在整体超时终止**本次**进程组并wait有限回收，forced_exit时cleanup不能标成功；正常结果另报peer/provider pending/quarantine/确认状态。progress.json仅有界脱敏trace/count，超时也保留；任何失败保留不自动下一轮。目录0700、文件0600，不输出stderr/provider body。shared server与client在隔离worker进程内不同async任务；不冒称独立手机或生产服务时序。

预期最小调用ASR1+文本4+TTS1；多句及原共享一次读重试最多文本9/TTS4。计费/免费额度未知，只记录真实用量；一次诊断不认证P12 median/P95或P15账单。root已明确授权此唯一轮，本工具没有额外额度审批门槛。执行须在既有全局锁内：

```
bash scripts/with-build-lock sudo -n /usr/bin/python3 scripts/v2_stage_probe.py --execute --source <固定SHA> --output /home/ubuntu/tech/v2-delivery/stage-probe-<SHA>-once
```

无默认执行，无all/下组入口。完整loopback fixture、meter负控、scope/cancel/observer/safety、read retry/repair和既有释放/TTL定向结果见同目录日志。原本轮开发失败日志另保留，不把最终通过倒写成首次通过。

计时采样收敛：ack_received/ack_progress/compact_skipped只各保存首次时间，另以三个固定key的饱和整数计数（上限2^31-1）统计；不保留scope集合，不提高128行。其余关键阶段仍按原门限记录。61块真实loopback TLS的合成provider对照已证明eof/released/reply_end仍可见，首次/effective ACK保留。原8e22唯一真实报告truncated=true不改、不重新执行；这个采样修正仅有离线证据。
