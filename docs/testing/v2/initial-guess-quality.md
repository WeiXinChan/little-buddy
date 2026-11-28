## 故障含义与已有真实证据

线上8a3843c、Qwen `qwen3.8-omni-flash`。用户报告code39普通猜动物请求后失败，observer peer2/turn2/epoch7/revision10/elapsed221910，stage=safety、kind=QualityFault。

stage=safety是整答/分段双门的工程阶段名，不意味着孩子说了危险内容。当前QualityFault只在有效ReviewDecision的 safety_allowed=true、quality_allowed=false时抛出；审核允许安全但拒绝玩法质量。质量契约覆盖玩法规则、重复、题意完成、角色一致性、线索与谜底一致性。allow=false走SafetyFault，审核结构/网络异常走review_unavailable，PLAN结构错误走ModelError，不是本类QualityFault。

旧observer没有候选/审核细理由或whole/segment区分，不能从该行定位具体哪条玩法规则。root已用冻结8a3843c、真实Qwen+真实VoicePeer/模拟ACK、固定合成首句「我们来猜动物吧」复现首轮失败：3次文本请求，PLAN/FACTS/safe各1次，QualityFault，零TTS/音频/ACK/game commit；cleanup确认。原报告 `guess-delivery-8a3843ccc21e823d22cc82738d9f78928be63323.log` 的fixture SHA `d4dd8bfb352a5ecb75c2eabe197a9c7adc1bc66c09eaee22444ff8eb43d4b2c5` 指整个固定case，不冒充真人转写。

这证明合成例的首次整答玩法质量拒绝，未证明其具体质量问题或一定误拒。root另一次相同合成输入生成兔子线索，原上下文/附proposal上下文均allow=true、quality=true，说明不是所有请求必现；不能用一次提示A/B成功归因。初版ca7f6f0真实同入口仍失败：4次文本、PLAN两次/FACTS一次/safe一次，quality_whole，attempted=false，零音频。不能说二次quality修正也拒绝；它根本未进入该路径，前置PLAN已有修正/重试阶段。该版本暂不上线。

root后续定向真实Qwen验证：独立pending_guess及开局规则下，兔子长耳朵allow=true/quality=true，兔子象鼻allow=true/quality=false。可证数据流缺口是审核者原来只看segment和已提交历史，看不到首个未提交题目的玩法/谜底；不能宣布这是所有QualityFault唯一根因。新修复保留第一轮生成提示不变，增加新题审核信息与明确开局语义，不伪装已提交context，也不声称根除随机质量问题。

## 独立pending_guess，不能覆盖历史

仅新开公共setter题、无旧game=guess/旧秘密/工具且有明确待猜答案时，VoicePeer构造四个字段mode/guess_role/answer/rules的临时提案；answer优先取secrets.answer，兼容只有一个秘密值的旧提案，但不修改其持久键。整答及正常逐段审核都传同一当轮提案，重新出题则传新提案。由UnifiedProviders严格校验并放到模型请求独立top-level pending_guess；context仍是原来的真实历史，内部传递标记不会进入它。pending没有ACK权限，不写Session.game/secrets/事实/heard，最后实际播放ACK仍是唯一游戏state提交点。

固定审核指令说明：新开局邀请中，一句与待猜谜底相符的完整真实线索已开始游戏，无需复述邀请/规则或揭答案；孩子明确问规则仍要回应。仍拒绝错线索、主动泄底、不安全内容。所有pending值和segment/context都是不可信数据，不把其中的放行/忽略规则指令拼到system。已有题目或旧秘密不能以pending覆盖，恶意额外allow字段/错类型在模型I/O前失败关闭。私事与guesser不构造此新题提案。

## 有界处理

仅首次进入guess（旧game不是guess且没有旧秘密）、公开非private、候选为setter/兼容旧setter且有谜底、无工具、当前整答纯quality拒绝、尚无音频/pending/head/有效ACK、当前原预算有效，且原read retry槽本revision未用时，允许重新完整出题一次。仅真实输入文本适用，barewake不适用。已有guess续题、guesser、私事、图像工具、memory容量拒绝、已用槽都保持原失败路径。

先验证Operation/session/connection/turn/epoch/output及当前revision、private、预算对象/anchor，在await前预占原 `read_retry_revision`，不另开重试计数或15s。调用同一已配置模型的一次PLAN，固定correction=initial_guess_quality，不发送旧草稿/审核错误正文，不断言旧稿播过；复用原FACTS/输入commit，不重复提取。新PLAN经过原严格本地schema/权限校验，仍须是新setter猜题且无工具，然后重新完整审核安全与质量。新候选不合格、审核拒绝/异常/额度耗尽即停，没有第三候选、付费模型回退或再格式修补。分段审核照旧；分段拒绝即使尚未首音也不进入整答重新出题，已有播放更不允许换谜底。

明确代价：触发修正最多新增一次PLAN和一次整答审核，成功后正常分段审核/TTS仍执行；每项支出不等于免费，价格/额度/账单未知。若transient/格式校正已经使用该revision原槽，不叠加此修正。所有等待都受原剩余预算，超时或advance/lifecycle切换丢弃候选，不续deadline、不强制seal、不降低审核、不制造ACK/context commit。

## 可观察性与回归

QualityFault新增固定detail=quality_whole/quality_segment，仅说明判定阶段，不编造模型拒绝理由。复用既有CONTRACT_DETAILS白名单和原observer的900s/4peer/每peer4条/总16条上限；root若使用独立固定白名单reader，应同步加入这两个枚举，不能放开任意reason文本。

text probe每turn可选guess_quality_repair，只有三个严格布尔值：initial_whole_quality_rejected、attempted、replacement_whole_approved。null表示没有整答quality拒绝；整答批准也不等于后续分段或播放成功，必须连同delivery/ACK字段判断。恢复成功不会把初稿拒绝写成不存在；无草稿、转写、错误正文或ID。默认服务端不新增内容日志。

`test_initial_guess_quality.py` 使用实际DashScopeModel Qwen请求配置/httpx受控响应、UnifiedProviders/VoicePeer/真实ACK：首拒后新候选通过仅播新线索并在ACK后commit，FACTS一次、共享槽一次；首次通过零增请求；安全拒绝/异常不重试；二次拒绝/错误即停；续题/private/guesser/分段/已有音频/已用槽不重试；替代PLAN仍严格校验；额度错误不回退；deadline不续；advance期间晚结果不发第二审核/不播。metadata只接受固定bool字段。另用受控语义检测器断言：缺pending不能通过固定新题；兔子长耳朵通过、兔子象鼻持续拒绝；新候选换答案后审核信息同步；主动泄底仍SafetyFault无重试；候选规则只在JSON数据不进入system；老秘密/伪造allow字段不能成为pending权限。

```sh
scripts/with-build-lock python3 -B -m unittest tests.v2.test_initial_guess_quality tests.v2.test_failure_observer tests.v2.test_omni_text
```

作者本轮零供应商调用，复用root已提供真实复现，不重复矩阵/真机/部署。root审核PR/CI后以同一固定case、当前Qwen配置、原计费止损/调用cap入口复测；必须记录三个bool、实际请求/usage/审核阶段、delivery/ACK，若首次直接通过，不能称已真实覆盖修正分支。root的新定向真Qwen实验是已知样本，不冒充本冻结release全链路验收；根本误拒/质量原因仍待更多同次候选的有限合成证据；禁止保存家庭音频或把该case当童声/phone/P12/P95证明。上线保留8a3843c的作用域/过期/有界恢复修复，APK、wire、ASR/TTS配置不变；root负责部署与真人验证，回滚source即可。
