# PLAN偶发失败诊断与有界纠正提案

本批明确依赖PR99 head2d86b4b的异常诊断通路，单独追加PLAN诊断；PR基于PR99分支，不包含PR97/98源码，不能称已包含root本地233b6cff组合。根main基线75dfeecc。PR97句数门禁现有异常字面量story turn sentence limit通过同一ModelError构造器映射plan_sentence_limit；本批只检查该标签映射，未在本分支重复执行缺失的PR97句数门禁。root组合时应保留97门禁/98提示词并复核。

## 已证明与未证明

原remaining-case-story-moon-233b6cff.json逐字保存：首轮68帧/68ACK、game提交、TTS确认退出；第二轮PLAN complete返回后ModelError、0帧/0TTS/无新game提交，上一轮已播状态保留，清理confirmed。故障在PLAN本地契约路径，但无原PLAN，不能断言就是句数。第一次“飞船嗖地…”发生在孩子第三轮慢飞规则之前，也不能借后续规则反推第一轮违反慢飞。

可能失败组：JSON content类型/容量/重复字段；PLAN根字段集合、action/mode枚举、rules类型/长度、roles数量/项、secrets结构/项、sentences类型/项数/长度、anchors类型/索引、tools结构/description用途、PR97句数门禁。JSON语法错误原类型JSONDecodeError和非hash枚举TypeError不是当前报告ModelError类别；HTTP envelope失败与该次complete ok=true不符。没有原候选，以上仅候选，不把48PASS当根因证明。

## 本批诊断实现

保留ModelError('plan'/'anchors'/'tool schema'/句数标签)原异常类和固定消息。拆分原短路条件为同序等价校验，附plan_structure/action/mode/rules/roles/secrets/sentences/anchors/tool_schema/sentence_limit固定码。非法不可hash枚举/工具kind原TypeError仍保留并标记；未知文本不当新枚举。沿PR99异常实例携带，不使用并发可覆盖的全局槽，不输出候选正文、动态key、原异常文本或计数材料。tools描述安全不合格原来丢弃工具的行为未变，不把它伪装成PLAN异常。

## 纠正方案（本批不启用，待审实施）

目标是生成合法单句并真实交付，而非只增加拒绝。先将已确定的当前显式句数以固定数字约束注入PLAN请求/schema的sentences.maxItems（仍不能代替段内句界检查）；模型要一次给出连贯单句及与该句匹配的anchors/state，不能后删句或截断。继续由模型理解内容与规则，不预编故事正文。

收到plan_sentences或plan_sentence_limit这类明确可纠正固定码时，最多一次重新生成完整PLAN；只发同一原输入、该次冻结授权context、固定纠正码及有界句数，不回发无效候选正文/未播剧情。其它结构错误先诊断，不开通用无限自修复；安全拒绝、来源错误、未知或撤销不借此重试。纠正返回仍须完整PLAN/句界/anchors/工具校验，再走原整段/逐句安全审核，最后原ACK提交，不能绕审核先播。

必须复用原ResponseBudget.read_retry_revision跨PLAN/FACTS共享的一次读取重试额度，而非额外自建一次；若已用/剩余时间不足/已有输出或状态已变化，停止原任务。每次I/O前后重验operation/epoch/revision/会话与冻结上下文身份；private/handoff/重plan须使用各自原授权上下文，不能借旧共享上下文修复。没有TTS/图准备/状态副作用的初次提案才能纠正；FACTS预取不重复调用，继续原发布位置与清理责任。取消、过期、HOME、管理暂停、换人后不纠正/不复活。原45s/24calls和生产表达预算不抬高，修复调用计入现meter/usage，不能承诺免费。

需要的离线屏障：首提案无TTS/无状态，纠正单句通过审核+末帧ACK后才提交；纠正仍违规/预算已用/撤销/晚到/私事重plan/安全拒绝均不发布，事实仅提取一次，stubborn取消仍隔离。正常一人一句真实模型是否因此可交付，要由root在独立QA后以原story-moon有限复验；当前原真实FAIL继续OPEN。若新诊断证明非句数问题，应按实际固定码调整方案，不能先验加句数重试。

## 本批离线验证

4新增方法（含12字段组反例）＋受影响44方法，48唯一PASS/0FAIL/0SKIP，diff通过。实际VoicePeer第二轮模拟anchors错误证明首轮ACK状态保留、第二轮无新TTS/无提交、无额外PLAN重试及报告不含输入。正常可选默认字段不变；非法枚举保留TypeError；未知错误文本不导出。它是合成故障，不复现原未知PLAN响应；本批未新增自动重规划/云调用/部署/设备或secret/config操作。
