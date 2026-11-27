仅准备，0真实云/ASR/TTS/图片/手机/部署，未占长测锁。生产基线main b568ef4730b0e30552bfc4577915bbec1afa6a61；独立测试分支，不修改产品。v2_closeout_probe_pin.json核验该基线backend/scripts及固定帮助文案字节，不接受任意source/config/输入文本路径。复用已审v2_semantic_recheck生产VoicePeer/Session/PLAN/FACTS/safe、实际heartbeat/Session ACK、异常/任务清理/父监督路径，仅将case显式单选及增加合成隐藏答案见证；不复跑G02/G05。

四个命令彼此独立，无all/循环入口。root当前仅执行第一条，后三条只列供逐组审阅，前组失败不自动续组。各自新输出目录，不能覆盖已有失败：

```sh
python3 -I -B scripts/v2_closeout_probe.py --case guess-object --execute --acknowledge-quota-not-live-verified --output /home/ubuntu/tech/v2-delivery/closeout-guess-object-b568ef47-once
python3 -I -B scripts/v2_closeout_probe.py --case story-forest --execute --acknowledge-quota-not-live-verified --output /home/ubuntu/tech/v2-delivery/closeout-story-forest-b568ef47-once
python3 -I -B scripts/v2_closeout_probe.py --case adventure-sea --execute --acknowledge-quota-not-live-verified --output /home/ubuntu/tech/v2-delivery/closeout-adventure-sea-b568ef47-once
python3 -I -B scripts/v2_closeout_probe.py --case association-flying --execute --acknowledge-quota-not-live-verified --output /home/ubuntu/tech/v2-delivery/closeout-association-flying-b568ef47-once
```

每条固定3轮、一个独立Session；24次模型请求上限：每轮PLAN+FACTS初次共2，生产共享一次重试/修复最多再1次，整段safe1+最多4句safe，共8次，三轮24；只有VoicePeer.read_request的原共享read_retry_revision/CAS可决定重试，每次max_tokens1400/nonthinking/严格json_object本地校验；组45秒、父55秒、HTTP10秒，原生产响应预算不扩。Meter仅限制声明的阶段最大量：每类read<=2且PLAN+FACTS合计<=3，safe<=5；它不授予重试。生产允许的第二PLAN或FACTS不会被一刀切拒绝，无fallback/harness额外自动循环；network/timeout先保留原生产重试机会，真实终态失败后不继续下轮。若走超出本固定公开场景的私事重规划导致超过声明阶段容量，应记录mechanical_budget/harness_budget_stop，不算模型质量失败，组失败/未确认清理停止。12次/1440字符仅合成Speech上限，不是真实收费TTS；ASR输入为固定text，ACK合成，不代表声学/设备。模型仅1017，runtime只读现有V2 service.env/dashscope-api-key，配置不匹配拒绝，无图配置。额度确认沿既有授权：acknowledge表示未实时核实，不声称实时免费only，不额外索取用户操作；历史截图/控制、quota unknown、planning非账单写admission。

result.json保留每轮输入、实际完整ACK正文/segments、公开game前后、synthetic_hidden_before/after、fixed failure/local_help、用量未知/差量、阶段计数及清理。hidden仅此固定合成场景中生产Session.secrets的快照，不导出任意用户会话或原凭据。猜谜人工应比对隐藏答案是否在未揭晓完整ACK中泄露、线索与隐藏答案是否一致、用户猜测/交换后是否按当前规则继续，不能凭roles/rules或单词出现判过。没有记录秘密的原报告不回填猜测答案；semantic_pass恒null。报告partial_unknown/未确认清理必须保留失败，父强杀不能标健康。

N02单独命令（最多2PLAN，无FACTS/safe/TTS/ASR/image网络调用，输出候选不是已播放）:
```sh
python3 -I -B scripts/v2_closeout_probe.py --case memory-compare --execute --acknowledge-quota-not-live-verified --output /home/ubuntu/tech/v2-delivery/closeout-memory-pair-b568ef47-once
```
同一生产Session先记录角色/禁止传送/先月亮站后钥匙/否定/旧钥匙与最新绿色钥匙原文来源，再ACK关键情节+角色规则。两份context都在最新事实录入之后生成；先full，再实际compact删除背景，compact_returned/revision/heard数量/同Session digest及完整两个payload/hash保留。facts与game严格相等，text相同；只heard压缩不同，不把新事实只喂compact一份。expected判据仅本说明供人工：不可传送/孩子船长瓦力领航员、先后、否定不翻转、新位置应优于旧位置，不能把模型复述关键词当正确使用。固定问题不含expected答案。两次providers.plan真实严格校验无repair/重试，逐一完成，无模型生成候选进入Session或播放，第二失败保留第一候选/固定错误，模型用量delta缺失仍unknown。

默认无--execute仅计划、无credential读/网络；必须指定case，不存在默认整组。internal_worker仅显式内部入口，父PID检查不是权限认证。最终9项离线方法PASS（本地模拟model）：单组选路/同Session与隐藏快照、单选拒all与G05、同最新事实实际compact、生产PLAN恰好2候选、第二失败留第一、第三请求拒绝/default无配置、最终main pin；实际VoicePeer句数修复成功2PLAN+1FACTS并完整ACK、驱动第三PLAN机械拒绝。不把这些当真实模型语义通过。root按已有授权首个guess-object三轮执行后人工判读再决定继续，未授权author自行执行云。

修订：旧准备head4684353限制第二PLAN过严，现后继提交取消该限制；不修改旧G02/G05脚本/17call实测，不重复执行。N02对照保持直接providers.plan两次（非VoicePeer响应），不增加repair或播放。admission no_automatic_retry指harness不自行重跑，另production_shared_retry_preserved=true如实标明产品一次机会保留。24次*1400输出token理论上限33600，不等账单硬上限。
