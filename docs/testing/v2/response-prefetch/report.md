## 首音频关键路径与最小业务优化

基线main4f991de1e2f18eb3f79db03ee1b217a6d4daa0db（含已部署语音释放/心跳修复）。本批仅FACTS/PLAN预取；不改模型、整段/逐句审核、TTS、.5秒释放、lease或输入预算。0云/设备/生产配置/部署。

### 原始证据与P12边界

P12（docs/v2-requirements.md）：完整表达实际结束到有效音频median≤2s、P95≤4s，占位语不算；P15约3元/有效互动小时需账单。原组合33d333b6报告逐字保留：两轮完成，第三轮因整个probe45秒超时终止，不能只选成功轮宣称三轮成功。

| 阶段（秒） | 第1轮 | 第2轮 |
|---|---:|---:|
| PLAN | 3.893 | 2.872 |
| FACTS | 1.866 | 1.368 |
| 整段SAFE | 1.035 | 1.721 |
| 首句SAFE | 1.676 | 1.963 |
| 四段串行合计 | 8.469 | 7.924 |
| 首传输音频前其余未归因时间 | .595 | .775 |
| 首传输音频实测 | 9.064 | 8.699 |
| 整轮实测 | 16.392 | 16.037 |

报告只有首传输音频，不是手机有效可听确认；不计算2样本P95冒充P12。其余时间含TTS建连、首帧/一块前瞻和本地调度，不能精确全归TTS。只按原阶段耗时不变估计，FACTS/PLAN重叠后约7.198/7.331秒（理想分别省1.866/1.368秒），不是云实测保证。即便以后两道首段审核也等价并行，理想约6.163/5.610秒仍大于P12目标；并发配额/服务端排队也可能抵消收益。

### 已实现：只计算并行，不提前提交

UnifiedProviders.facts(text)的请求体仅dict(text=text)，schema/provenance验证仍原实现。PLAN原本在record_input之前取Session.context(query=text)，故FACTS计算结果原本就不应进入本次PLAN上下文。新增一个task与PLAN读取重叠，开始I/O前检查原operation及response_revision；不能借之后的新revision发旧输入。只在原facts阶段await该task，随后重新operation.ensure/revision验证，再调用原Session.record_input。没有提前写事实、切private、换Session、改状态/播放。

已有private_mode时不预取，private→shared重规划保持原串行顺序。由公开会话进入private时，提取仍只有相同本轮文本，无旧上下文；须先按PLAN置private后才能提交。handoff在旧Session撤销前取消/回收并丢弃预取；end不提交预取，先确认回收再告别。非法来源、容量拒绝仍走原原子验证与memory_limited降级，降级语句也经原审核。图像/未播谜底/角色状态仍最后已播ACK生效。

新task用原track_retired登记；await使用shield，取消不会无限等待吞取消的子task。结束/失败/撤销都在finally最多.3秒观察取消；不能确认则quarantined且保留retired句柄，无后续输出/复用。嵌套finally仍清generation_scopes/图片等，即使重复取消。没有wait_for伪硬界、自动后台重试或新框架。现有read_request与同一ResponseBudget.read_retry_revision保留，全轮至多一次重试；两读取并行时由先预留者使用，不新增各自重试配额。

代价边界：普通回复仍各一份PLAN/FACTS，不增正常调用量；在知道end/handoff之前可能已经发出至多一份投机FACTS（以及共享的原一次重试），即使取消也不能保证免计费。其结果从不提交，root有界复验需记录该额外情形，不宣称零成本优化。不对已知私事重规划做投机。

### 审核、提示词与后续路径

整段及逐句SAFE全部保留原顺序/参数。单句本来就只审核一次；多句整段语义检查与逐句在当前已播上下文中的检查不等价，不删其中之一。本批不并行两审核：冻结context等价尚未完成独立证明，后续句可能已见新的heard/状态。安全许可始终先于TTS/播放。

空真实Session＋固定合成输入离线量化：SYSTEM1606 UTF8 bytes；PLAN指令4667/data312，FACTS指令2388/data24，SAFE指令2004/data291（字节非token，不代表真实长会话prompt）。当前max_tokens1400是上限，不是实际输出1400；缺每阶段tokens/首token时间，不能证明压输出上限必然提速。不裁掉事实原文/否定/私事projection/memory.omitted_sources，也不靠固定一条玩法或占位音刷开口。精简可选工具说明/按task定制schema只能另审，不在本批偷删语义或降低审核。

### actualVoicePeer离线证据

14新方法：FACTS在PLAN屏障前完成仍无facts/recent提交或TTS；相同实际UnifiedProviders FACTS输入在串行依赖/并行两组完全相同；private、已有private重plan、handoff、end、epoch/revision撤销、预取尚未开始即撤销、非法来源、容量故障、共享retry及吞取消task等均有反例。actualVoicePeer对照仅用合成模型的FACTS依赖屏障模拟原串行路径：同一生产VoicePeer，PLAN80ms/FACTS60ms，首传输音频147.44→84.15ms；这不是旧版云或模型速度基准，预计收益不能直接外推。

受影响103方法PASS；原独立metadata3＋清理falsifier2 PASS，总108唯一/0FAIL/0SKIP。早期清理测试仅期待一个在途模型请求，因现在合法同时PLAN/FACTS而出现1FAIL；原失败日志保留，断言改为精确各一份PLAN/FACTS且无SAFE/后续stage，不只把数字放宽。编译/diff通过，不重跑后端全集。

### 用户最新Flash授权：最小后续接入点（本PR不换模型）

用户已允许慢时评估Flash及语音Flash、不自动授权付费回退。候选deepseek-v4.1-flash、deepseek-v4.1-flash-1017、qwen3.8-omni-flash的权限/额度需root重新有限核实，历史403不能推断当前不可用，也不把本地计数当账户免费余额。

文本现有接点：runtime.settings/FIELDS的DASHSCOPE_LLM_MODEL，DashScopeModel.__init__(speech,model=...)。但complete当前仅qwen4-max使用json_schema，其余走json_object，仍须本地PLAN/FACTS/SAFE严格校验。下一批应在同一VoicePeer/case/安全与费用门禁下，由root分别显式注入候选，核JSON/玩法/审核/取消/usage及速度；需同时更新受控preflight.MODELS和harness固定模型门禁的明确测试候选接口，不能直接改全局TEXT_MODEL。

尤其image_review/image_runtime也依赖TEXT_MODEL且锁定图审模型；不能把全局常量换成DeepSeek，连带替换视觉审核。若保持安全审核用qwen4而只对PLAN/FACTS试Flash，应显式分配task模型与独立usage，不伪装单模型计费。omni是否支持相同文本结构化接口/语音协议尚未核实，不能盲目当文本API或CosyVoice替换；语音评估需单独核支持的端点、音色/采样/流与释放契约。此次0真实调用、不改配置，无自动paid fallback。
