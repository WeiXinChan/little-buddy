# 持久句数约束：原PR97增量

原root反例JSON和46ce6426真实三轮PASS报告均逐字保留。原反例在head9367518实际obeys_turn_limit复跑FAIL（original-failure.log）；修后同JSON输入与expected_accepted断言通过。三轮真实PASS仅证明该样本正常，未复现233b6cff第二轮失败，不证明原PLAN未知根因已修。

不再靠模型持续复述规则。服务器从本轮明确句数/取消指令或已提交约束生成本地_story_turn_limit提案；模型原始JSON不能带这个字段或turn_limit，否则原严格字段集合拒绝。仅最终已播ACK把约束作为Session.game.turn_limit的一部分原子提交，复用原state deepcopy/容量/private门禁，没有并行可提前更新的旁路存储。None是明确取消回执，防止下一轮模型旧rules意外重新启用限制；不出现字段表示尚无约束。

后续PLAN和句数校验优先已提交结构字段，模型换词甚至单方面action=change不能抹去；孩子明确改数/取消仍优先，离开故事清掉随玩法的约束，private输出不提交公共state，handoff清空。内存容量回退沿原公共约束，不把没被接受的新句数假保存。所有这些仍在原预算/scope和ACK位置，未后删句、未扩大存储上限/lease。

旧会话没有结构字段时，有限每人/每轮等+说/讲/接+数字句数语法解析已提交rules，第一次合法完整交付后迁移；接是原反例“一人接一句”的语法动词，不建立无限模型同义词表。无法解析的旧文本不能凭空还原历史承诺，仍需语义复核。当前孩子已解析的约束一旦提交，即使未来rules完全换成“接续精彩故事”仍有结构字段可证明。句数取消补有限“取消句数限制/不限制句数”等语法，复杂引语/嵌套否定/未知措辞继续不声称全面覆盖。

生产仅改companion/story_rules、voice接state、Session允许额外可选typed字段（None或1–4整数，拒绝bool/字符串/越界及非story携带）；不改Android/wire合同/云资源/模型/安全审核或.5秒释放。

最终61作者定向方法PASS（8新增＋53原受影响），QA原4方法原样PASS，65唯一PASS/0FAIL/0SKIP；编译/diff通过。覆盖root原反例、任意模型改写、legacy迁移、伪造receipt拒绝、1→2→取消→恢复1→取消→离开、最终帧部分ACK/最终ACK、未ACK撤销、private/handoff/容量回退与核心state类型/拷贝。

中途测试夹具误用不存在的emit及ACK循环未让出事件循环，修为真实Session.send和有界让出循环；fixture-debug/new.log保留该开发失败，已终止并回收确切自有测试子进程，不作为产品失败或PASS分母。root原反例输入/assertions及QA原断言未改。原始失败、原三轮PASS与本地模拟证据分别列出，不伪装云复验。作者0云/设备/部署/子agent。

与PR99/100组合时须同时保留本typed字段提案/Session schema/ACK门禁、PR100固定plan_sentence_limit诊断，以及PR98人格提示；本分支不冒称已经包含那些未合源码。等待独立QA增量后由root审合/必要实测，PR97此前未知第二轮PLAN故障仍独立OPEN。
