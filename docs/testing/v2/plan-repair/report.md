# 已证句数失败的有界完整重规划

依赖：main7f3bd941d4af8a7c283f68ceda16fa41bfff532d已含98/99/100/101，显式本地集成冻结PR97 fc48e3078db42bcdc35f5e3de459a9d75608d070，集成快照e43806488ce744219ca1043d87a2b85dcf5095a1。冲突仅import与相邻提示词，保留人格/句数两组约束和原诊断。没有改root树/合main。PR102测试客户端修复仍独立，最终组合应一并保留。

## 证据边界

root原remaining-case-story-moon-c130bfdf.json逐字保存：本次已明确plan/ModelError/plan_sentence_limit、0TTS。可据此针对句数纠正，不能反推233b6cff旧未知故障。作者没有云调用。旧集成无纠正源码下，新离线反例确认只能一次拒绝，没有两次规划（old-no-repair-failure.log）；最终合成修正成功不冒充真实模型效果。

## 实际实现

首次PLAN多传服务器生成的server_constraints：story_sentences_max及correction(null)。从本轮明确指令/已提交typed约束/legacy已提交规则确定数值；未知保持null，不擅自默认一人一句。只对story continue/change适用，不能阻止合法离开/私事。提示要求完整生成一致sentences/state/anchors，不剪裁候选。JSON Object与原全部本地校验不变。

若首次未知数值，但模型自提“一人接一句”而输出多句，本地验证失败只把已计算的1–4整数上限放到异常的repair_sentence_limit，不带规则正文或无效句子。纠正请求使用这一个有界数字和固定plan_sentence_limit码，不把无效候选原文发回。若原本有服务器约束，必须保持相等；明确取消/null不能被hint覆盖。纠正新PLAN不能靠重写rules逃过该次数字上限，成功后仍待原最终ACK才将typed约束提交。

VoicePeer仅在ModelError+固定plan_sentence_limit+合法整数上限时允许repair_plan端口；保留网络/timeout原重试逻辑，双方共用ResponseBudget.read_retry_revision，在await前预约，不额外建额度。二次调用不再包递归重试。未知结构/来源/安全/quota不进入纠正。已预约同revision、已有pending/已确认输出、prepared/待唤醒、private模式/私事上下文及切回公共的重plan端口均禁止；换人/epoch/revision/operation/原budget对象变化由原门禁拒绝。全部使用同一原deadline，remaining不足不调用模型。

第一次与纠正均由同一脱离副本快照构造请求；模型拿到另一个深拷贝，不能改写本地验证context，避免首次adapter修改数据后“丢失”约束。无效候选不进新请求、不进Session/context或日志。正常FACTS预取不重复，仍在原接受位置提交原输入来源；纠正仍须完整PLAN/工具/句界/安全审核/ACK，不前播。取消/迟到/未知scope不能借修正复活任务；原资源.5秒边界不变。

多轮harness原合成输入没有给ResponseBudget原始speech边界。本批仅在每个新合成表达开始初始化该表达的15秒预算并speech(0)，与真实客户端首输入帧相对应；重试/纠正没有重建预算，生产路径也没有新建/延长。仍是合成文本入口，不冒称ASR。45秒/24model/12TTS1440字符总case上限及meter覆盖纠正调用，usage未知不当0。

## 离线验证

10新增＋64受影响，共74唯一PASS/0FAIL/0SKIP（targeted.log）；编译/diff通过。实际VoicePeer覆盖：先提数值约束、无效→合法完整单句/最终ACK、第一轮模型自提约束时仅数字纠正、snapshot不被adapter污染/不回传坏句、FACTS一次、再次失败终止、审核拒绝、未ACK取消、revision/管理/cancel、已用重试/private/切回公共/已确认输出、FACTS与修正两种预约顺序、原deadline过期、quota闭合及伪造安全tag不修正。三轮harness请求总量10=4PLAN(含1纠正)+3FACTS+3SAFE，所有调用进分母。

开发初测两个FAIL保留：adapter污染验证context及未调度FACTS的夹具期待；分别用隔离模型输入副本和明确FACTS已开始屏障修正，未放松产品校验。new.log为中途9方法日志，最终以targeted.log 74为准。原233未知故障/原c130已证句数FAIL均不刷绿；需要独立QA后root有界真实story复验确认模型可交付。0云/设备/部署/子agent，不据离线通过声明整个R03/R09/P12/A36完成。
