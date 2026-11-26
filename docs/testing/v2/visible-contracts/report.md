本批修复模型可见契约，不能证明原真实返回值或真实玩法质量。

依赖：main37535eae + PR105 03786d9（FACTS可见契约）+ PR104 3aa8902（stop身份/期限）；集成基点e04410ed。未回滚105。原bfdf22c1的真实cross-game失败逐字保存在live-original-plan-anchors-failure.json；只证明plan_anchors，不能推断1-based、具体key/value或secrets匹配错误。没有云调用、DNS、设备、配置读取或部署。

事实与修复：
- JSON Object模型的response_format不传严格schema；之前只有FACTS显式呈现schema。现在request统一将同一份deepcopy schema呈现给endpoint/PLAN/FACTS/SAFE/COMPACT，并继续传给adapter；FACTS不重复呈现。明确枚举为单一值，示例均为实际JSON，不改变模型/重试/截止/审核/ACK。
- PLAN明确0-based且index < 本次sentences长度，静态0..3不是动态长度；anchors键1..40、最多16。schema增加propertyNames，并把secrets的静态79/999上限与既有本地严格<80/<1000一致。原本地拒绝集合不变。
- anchors是已播句子的标签索引，不是秘密引用表。隐藏谜底继续保存在secrets，续题恢复原unrevealed，不凭模型新猜测换题；私事/未播内容不可成为公开锚点。schema本身不能证明这些语义/隐私条件，原审核与最终ACK仍必需。本批没有新增secret mismatch检测或对应故障归因。
- 保留plan_anchors和ModelError('anchors')，新增可选固定detail：anchors_container/anchors_count/anchor_name/anchor_index_type/anchor_index_range。VoicePeer和探针只透传白名单；不记录原异常/候选正文/URL。

验证：7个新增方法，10个非法anchors子例走真实DashScopeModel合成HTTP→UnifiedProviders→actualVoicePeer；FACTS-start屏障确保与原2模型、0TTS场景一致。容器/数量/空或过长key/bool/string/float/负数/实际数组越界均拒播、不提交、不重试；合法0/末索引接受。正常三轮隐藏谜底只在unrevealed，公开played只含实际线索。安全拒绝仍0TTS。五阶段payload可见schema恰一次，JSON Object/nonthinking不变。schema与本地秘密长度边界一致。

最终受影响集合76方法：76通过、0失败、0跳过；详见affected.log（含7新增，其余为FACTS诊断/可见契约、PLAN诊断/纠正、并行提取、读重试、模型用量、记忆/隐私）。非法输入是上述正常集合中的负例，不冒称独立突变数。targeted.log为15方法定向通过。initial.log保留作者首次测试的断言失败：新fixture未等待并行FACTS启动、工具提示仍含管道示例、旧诊断精确oracle缺新detail；修复fixture屏障/提示后更新该oracle保留其他断言。

剩余：真实模型对新提示的兼容/语义质量须由root审合后有界复验，未证明原失败根因，更未以76绿替代原真实FAIL。schema增加的结构说明有token开销，本批不声称延迟/费用改善。没有额外修复重试；所有动态长度、秘密/私事语义仍由本地验证与原安全/提交路径负责。
