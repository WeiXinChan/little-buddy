# 剩余多轮执行清单与故事句数修复

基线75dfeecc0c6a608b8432012e6f0f3584abce4a05（已含指定92e58140）；两版harness/cases逐字无差异。本批不改harness/VoicePeer/协议/模型配置。无云、设备、部署。root的story-moon原报告逐字保留，机械checks全过不等于语义通过：人工报告三轮3/3/4句，违背当时一人一句规则；蓝星/慢飞禁传送连续性不能抵消此FAIL。

## 逐例顺序（不自动跑目录）

原12cases已具备A03四类各2主题/不同措辞/3轮，以及A04四类转换场景；它们只是覆盖设计，尚非实测通过。优先三个case如下，另两项不可省略或假称包含在其中：

| 顺序/case id | 每轮同步observer人工语义判据（均以实际ACK后快照为准） |
|---|---|
| 1 story-moon | 1接续孩子的小猫/飞船，不擅自代写双方多轮；如实际规则一人一句，回应全部内容只一句，不追加复述/追问/提示。2接住蓝色星星，保持角色轮流及上一轮已播情节，不重开故事。3慢飞、禁传送真正约束续写；不能规则文本写慢飞、剧情却瞬移。root已测FAIL，修后只由root决定是否复验。 |
| 2 cross-game | 1模型出谜孩子猜，未公开答案不漏。2明确停止猜谜进入轮流故事，不要求猜完；只沿用公开动物信息，不能因“刚才的动物”泄露尚未播出的秘密答案。3接住孩子给的小船并续写，不退回猜谜或凭空抹去公开剧情。 |
| 3 change-rules | 1水果轮流一人一项，不重复双方已播项。2本轮起红色水果条件实际生效，旧已播历史仍在。3接住草莓，选择另一合理红色水果，不重复草莓/旧已播项；仅rules含红色不足通过。 |
| 必要补项 exchange-question | 1模型出题、孩子猜；2孩子出题、模型猜黄色弯水果；3继续孩子出题，模型猜红圆可榨汁，不反转问答双方。逐轮核roles的归属及实际heard的行为，非两个角色词同时出现。 |
| 必要补项 abandon | 1孩子选路、模型向导；2立即接受放弃转chat，不要求闯关/完成任务；3谈云的形状，不复活山洞目标或向导设定。公开事实可保留但不是继续玩法许可。 |

“3个优先case”不能独立覆盖全部A04：cross-game没有交换出题，change-rules没有明确放弃。若root优先放弃，可把第三项换abandon，但change-rules仍须独立排队。A03另外主题/玩法仍逐项记实际状态，不以本清单报完成。

## 原入口/执行与观察边界

直接复用scripts.v2_multiturn_probe.run_case(case, authorized_providers, observer=sync_observer)。按精确id选一个case，传入原case，不把expect写入provider/context。动态图片必须None。合成文本跳过ASR/端点判定，真实Session/VoicePeer/PLAN/并行FACTS/双审核/TTS，模拟ACK，不证明实际声学。

同步observer(label, snapshot)接脱离原对象的深冻结context：game.mode/rules/roles、heard、recent、facts、memory、unrevealed/private/partial_unknown。root只在内存比对当前合成输入、实际回应和规则/角色/情节因果；不落正文或谜底。每轮机械mode/rule_role_terms/played_context/delivery仅必要检查。observer不能修改状态、异步调度或调用模型；异常停止并清理。输出仅label、人工判定/固定失败类别、metadata/hash/阶段时延/usageDelta，不输出快照正文。

正常三轮每轮PLAN1+FACTS1+整段SAFE1+每句SAFE n：3+n请求，即每case12–21请求（n为1–4）。一人一句正常12请求、3TTS；重plan/retry/compact也计入同一24请求上限，绝非额外额度。每case最多12TTS/1440 Unicode字符，每模型输入JSON及instruction各32768 bytes，生产request单次8s与总45s同时生效。Unicode字符不是供应商计费字符。FACTS/PLAN在同一事件循环预留call计数后才await，共享meter；并行不放大上限，事实仍在生产原提交位置受operation/revision门禁。

任一机械失败停止后续轮，无自动质量重试或整批重试；root人工语义失败也停止后续case。保留生产允许的read retry并计量。45s是协作执行上界，清理观察另有0.2s，不能保证物理中断任意吞取消协程；复用root独立worker/父监督60s。未确认清理时保留关闭meter和cleanup_handle，provider_reusable/usage_final=false，不继续下一例，不以pending0独自证明可复用。heartbeat经handle即时+每5s，仍受BatchState回收，未改lease。

按一个case一进程逐批审查；最多24模型/12TTS是调用上界而非币额账单硬上限。usageDelta缺失保持unknown，阶段时延含并行重叠不能简单相加当端到端。root外围受控provider做费用预留，P12仍需结束表达到有效实际音频实测，P15仍需含审核/摘要/retry/ASR/图片的实际计量/账单，不用免费截图或小样本宣称约3元目标达成。

## 最小修复及证据

companion.PLAN明确故事接龙每轮贡献、明确句数时不额外追问/复述/提示；本地窄防线检测显式一人一句规则下多段或段内多个句子，整项ModelError拒绝，在任何审核/TTS/状态发布之前。不截断、不改anchors/最终提交位置，也不额外模型调用。当前规则continue继承；明确change采用新规则；leave/private/end等不强留故事。

此为显式中文句数约束的保守标点检查，不是语义证明：单句内多剧情、引语/歧义句式仍需语义复核，不把单句PASS等同内容自然。未引入通用语义识别器，模型仍须按提示理解引用/否定和规则修改；未知措辞不声称完全覆盖。

原源码实际VoicePeer多句falsifier exit1保留offline-original-failure.log；相同输入/assertions修后通过。4新增方法覆盖多数组/单数组多句0TTS0提交、三轮ACK、旧规则被偷偷移除拒绝、合法改规则与leave；连同既有13harness方法17PASS/0FAIL/0SKIP。未重复旧全集。真实story-moon仍为FAIL，等独立QA/root有限复验，未冒称本地修复已证明模型遵守。

## QA97增量修正（替代上文旧窄cue实现）

QA原4方法在旧head446ed91原样执行：1PASS/3FAIL（before.log）；独立原输入/assertions及旧日志/报告逐字保留qa97/目录，未编辑。修后同脚本4PASS。

新增story_rules.py有界显式语法：每人/每次/每轮、一人/一次/一轮 + 可选只/说/讲 + 1至4/一二两三四句，及你一句我一句。按分句顺序解析显式否定与新规则，引用旧规则不作为指令。本轮显式规则优先；continue无本轮规则时沿用已提交规则；change使用新规则，不叠旧上限。取消句数约束返回未知/无上限（仍受原PLAN1–4项容量），不继承被否定的一句。不尝试无限关键词或完整语义解析，未知措辞仍需模型/QA，引用中直接颁布规则及复杂嵌套否定不声称全覆盖。

句界纳入英文句点；保护数位间小数点、常见称谓缩写和连续单字母缩写。省略号作为句内停顿；双语引用闭符不单独算一句。英文缩写/省略号可有语义歧义，局部词法规则不是完整语言学分句器；实际语义仍需复核。拒绝整提案，不后截断；两句规则也有2句边界，不能借新规则输出3句。

最终作者定向23唯一方法PASS（原17＋新增6），QA原4方法PASS，共27唯一方法、0FAIL、0SKIP；没有以重复导入算分母。覆盖真实VoicePeer否定改两句/每人说一句/ASCII多句拒绝、小数/缩写/省略号正常播放、持续规则继承/更改/取消、私事退出及无规则两句保留。原3FAIL及真实story-moon失败继续保留；离线通过不表示真实story已复验通过。无云/设备/部署/角色派生。
