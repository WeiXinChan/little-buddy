# Solo 后未识别输入的有限结束

基线 main `71c136e`（含152/153），本分支同步 main `6676d77`（含154）。code32 的实机触发类别仍 UNKNOWN：未取得服务端收到 probe 及 ASR/endpoint 处置的关联证据，不把离线同形复现称为现场根因。

## 可证明路径及修复

原 `_analyze` 将 ASR 空、ASR异常和 endpoint 异常都映射为 `decision meaning=unknown`；awaiting_input 和原输入期限未结束。真实 VoicePeer.run/wire 复现 solo 完整 ACK/reply_end 后，这三条路径均可在原15秒期限发 timeout。健康续轮及六次可取消 probe 可以正常 endpoint，故不支持普遍 turn/epoch 失配结论。

新实现区分：合法空 ASR、正常 complete+seal 后的语义 unknown，确认撤销旧输出后结束当前未识别等待，发原有 scope/decision；供应商、解析、配额、网络和安全错误发原固定 failure 分类，不作为成功 unknown。未完成/thinking 不强行 seal。没有新 wire 字段，没有额外 provider 请求。

一个 exact scope latch 阻止同轮尾 PCM/probe 重启识别。先执行原权限、隔离、协议及音频格式门禁；仅已确认的相邻 stop barrier 可迁移 latch，下一自然 advance 改 revision 后正常接收。清理前后检查 Session 对象、session/connection/turn/epoch/revision/private、原 budget 对象和 anchor；过期输入保留 timeout 及原 deadline，过期旧输出不伪装 unknown。旧 generation 的释放仍最多0.5秒，未确认/异常则 quarantine，不能清状态冒充成功。

Android 必须配套：仅当前 scope 的 unknown 在未过期时终止 gate pending，沿原 interrupt mute/stop/release 和 epoch stop，保持 awake；下一 speech 走 advance。不能 resume 旧音频、赋予管理权限或放宽15秒/TTL/capture guard。本后端 PR 不修改 Android，也不证明 nativehead 或手机完整回应已经恢复。

## 验证和保留失败

`tests/v2/test_post_solo_probe.py` 包含原 `_analyze` 的冻结源码及 SHA 校验，保留原三种 unknown→timeout 负控；相同生命周期在修复实现及认证 loopback TLS 上验证下一输入、完整 wire ACK、旧未播音频撤销/旧 ACK 无效、正常语义 unknown 和 incomplete 区别。独立所有权负控覆盖替换 Session/connection/turn/epoch/revision/private/budget/anchor、管理隔离、调用者取消、释放超时及失败、输入/输出过期和真实安全分类。

心跳测试曾在仅 enqueue 后越过原 lease，修正为等待实际 heartbeat_deadline 更新后推进 fakeclock，原失败保留，不改生产期限。首次相关回归缺 sparse checkout 内原始 QA fixture，补齐仓库文件；另一个旧管理测试直接 await 已取消任务，冻结原实现同样报 CancelledError，现显式观察取消结果并保留不得发管理事件断言。

最终命令（同 heavy.lock / 2GB，无联网供应商）：

```sh
scripts/with-build-lock python3 -m unittest -q tests.v2.test_post_solo_probe tests.v2.test_recognition_handoff tests.v2.test_stage_timing tests.v2.test_session_expiry tests.v2.test_management tests.v2.test_natural_management tests.v2.test_safety_help tests.v2.test_m04 tests.v2.test_m05
```

133项 PASS。原失败日志和最终日志随 issue 交接；实际 ASR/LLM/TTS/image 调用均0，TLS 使用合成 provider，ACK 不代表声学播放。15秒、0.5秒、TTL、权限和安全门禁不放宽。不宣称 P12 或手机问题已通过。

## 下一次定位建议（未实施、待 root 审）

如需要区分现场类别，在既有默认关闭、有界 Trace 中加入固定输入处置枚举：received / empty / semantic_unknown / endpoint_complete / supplier_failure / stale / cancelled。关联仅本地临时轮序和阶段相对时间、次数；不增加 wire 字段、不输出正文、原异常、UUID、URL或凭据，不增加 provider 调用或记录上限。本轮未新增诊断入口或实际刺激。
