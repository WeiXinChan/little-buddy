# A36/P14执行与采集准备

依据docs/v2-acceptance.md A36及docs/v2-requirements.md P14：60分钟混合互动，网络扰动、反复打断与玩法切换，观察资源/任务趋势、延迟和上下文。原readiness审计逐字保留。现有短设备回归不是此验收。

## 实现范围和运行

`python3 -m scripts.v2_soak --offline-seconds 3600 --output <私有结果文件>`

CLI只构造内置合成模型/TTS，不加载凭据、不联网、不操作设备。默认3600真实单调秒，120个固定计划slot、30秒间隔；到达尝试上限后等待剩余时长。缩短--offline-seconds仅用于离线验证，wall_60_minutes_observed按清理前真实观测时间计算，清理用时不能补足60分钟；full_acceptance/P14一直false。模块API run_soak可供root受控worker注入已授权UnifiedProviders，必须allow_cloud=True且明确CloudBudget(reviewed_bounds=True)，否则在任何I/O前拒绝。无云CLI开关/secret加载器，避免误用。

实际复用VoicePeer.run、handle、respond、Session及原operation/预算；双向有界JSON队列承接真实协议bind/ACK/heartbeat/stop，不直接调用Session.ack。持续同一peer/session观察，未按case重置上下文；自然到期/退出会失败停止，不擅自延长TTL或复活。合成文本在生产ASR/endpoint之后注入，非真实ASR；没有绕过PLAN/FACTS/安全/TTS/ACK状态提交。离线模型只是合成fixture，不证明玩法语义。

固定6步轮换：猜谜→故事→冒险中stop→联想含ACK延迟→故事含ACK丢失后stop撤销→普通聊天；重复20轮形成120个slot。正常行记录实际交付与当前game.mode，interrupt/drop须观测服务端epoch转换。注入ACK延迟150ms、丢失不ACK是模拟网络扰动；并非真实TCP断网、TLS故障或移动网络切换，drop后stop为主动安全收尾，不假称已重连。真实物理网络事件另待设备/网络驱动。

## 上界与所有尝试分母

固定最高3600秒观察、120attempt、720模型请求、240TTS、28800 Unicode字符、单attempt<=45秒（默认40）；模型原请求/VoicePeer预算仍有效。每次模型/TTS I/O前扣全局调用和额度，失败/取消/重试/审核/摘要均不退款，不按轮重新计数；模型instruction/JSON各32768 bytes，动态图片必须None且ASR端口拒绝。额度或供应商quota关闭全局门禁，不自动重试或fallback，停止后续slot。输出model_stage_calls(PLAN/FACTS/SAFE/compact)、失败/取消次数、usage前后delta；缺usage为unknown，不当0。

离线额度synthetic_units不是钱。生产必须由root提供审核过的每模型请求/TTS请求最坏费用预留（CloudBudget的整数micro-CNY）和总上限，并在Limits.allowance_units中显式给相同/更小总额度；无已审核费用边界则不执行。max_micro_cny/单请求预留由root按实际模型/输入输出/字符计费核定，不随便填合成测试的1。是本runner请求前预留上限，不是供应商账单或全账户免费额度证明；服务商后台/其它进程不受它计量。真实ASR/图片未执行、TTS/审核/摘要/retry实际账单尚需root对账，billing_bound_verified/P15为false。

所有开始attempt先插入结果行，失败/超时/取消均在attempted和failures中；打断另记interrupted_attempts，delivery_rate_all_attempts以全部attempt为分母，不拿4次交付/4当作6次总尝试全过。not_started明确因停止未执行的计划slot，不从失败分母移走已开始项。无自动整批重试。

## 收尾与资源

stop事件/调用方取消/超时关闭meters，再取消与有限观察transport、generation、heartbeat、采样和retired任务；不使用等待吞取消任务的wait_for假称硬超时。外层清理观察0.6+0.2秒，生产peer自身cancel_generation仍保留原0.5秒。未确认退出则保留关闭meter/probe_cleanup_handle，provider不可复用，不继续新case；任意stubborn协程无法物理强停，root必须使用独立进程父监督（观察预算+有限收尾余量，例如3610秒），不能在主服务内执行此长测。被隔离worker由父监督终止；无背景退出后完成承诺。

每30秒实际采样当前进程RSS/fd/thread/asyncio tasks与runner拥有的active session、operation、retired pending；保存最多4096采样，给first/last/max趋势，不预设“无增长”判PASS。不是整个生产服务全部会话统计，device RSS缺失为null。记录active_attempt/standby/cleanup时间；active_attempt不等于有效互动小时，effective_interaction_seconds未知，不拿等待和失败充有效时长。

## 手机及真实事件接口（未接）

本批allow_device=True始终拒绝device_driver_not_integrated，device_executed=false；不以backend-only宣称A36完成。后续设备驱动必须按本固定scenario/index驱动真实业务入口，并回传以下独立事件字段：

- attempt_started / expression_finished / first_effective_audible_reply / interruption_started / speaker_silenced / operation_completed / failure / network_transition / game_transition。
- 固定attempt index、受信采集层枚举(device_audio_observer/device_network_observer/backend_transport)、同一已校准单调时基及时间戳；无正文/PCM/凭据/URL。
- 明确是注入命令还是实际观测回执；command stop≠扬声器静音。device资源以数字RSS/fd/thread与时间戳另报，无原始dumpsys/logcat。

当前报告device_events=null，声学回复/静音时延null。first_text_to_transport_ms只是合成文本开始到JSON客户端收到首音频，不是P12有效可闻语音；ACK是模拟播放，不是实际AudioTrack/听觉。没有可用自动设备业务驱动，接口边界和必需字段已准备，真实手机/ASR/TLS/声学/对账/独立语义评估仍OPEN。

## 离线证据

8新增+13现有共享harness=21唯一方法PASS/0FAIL/0SKIP；真实1.3秒6步混合（4交付/2打断、分母6）、真实0.22秒调度等待、超时/quota失败、全局额度、默认云/设备禁、外部stop/调用方取消、stubborn取消有限返回/关闭meter/禁止复用、脱敏与资源不可读unknown。反例资源在测试finally显式释放回收。无60分钟运行/云/设备/部署；short-fixture仅0.2秒，不声称长稳成功。重型构建未运行，无占heavy锁。

## QA101采样修正

详见qa101/report.md：operation及retired实际容器变化后同步采样、attempt/取消/有限清理生命周期采样与周期采样并存。ring满后在线first/last/maximum保留历史观测，不用存活样本重算峰值。maximum字段仅观测样本最大值，非连续物理峰值；采样错误/unknown资源/未确认清理/失败不会resource_collection_valid=true，仍不改变P14/full=false边界。最终29唯一方法通过（26作者/受影响＋QA原3），原HOLD失败保留。
