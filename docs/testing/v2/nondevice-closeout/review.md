本批只落实N01/N02/N06，base main b568ef4730b0e30552bfc4577915bbec1afa6a61，独立分支。没有生产修改、云调用、生产反馈写入、部署/手机/新代理或占用heavy.lock；本地三项仅0.16秒，EC证书+真实loopback TLS/临时SQLite为轻量隔离执行，不是供应商或设备证明。

N01：semantic-review.json对六个已有真实模型/实际ACK/state报告逐轮独立判读，保留源SHA/原件hash、新增ACK正文和观察状态、拒绝/过拒两侧。输入为已有固定case fixture，报告本身没有原始request正文，明确标注这一证据边界，不把fixture当抓包。旧版本案例不直接继承为最终main通过，不以关键词/model自评打分。故事三轮保持单句/蓝星/慢飞，跨玩法沿用动物与溪流，规则保留红色且樱桃未重复，交换出题实际由答题响应见证，太空角色交换由称呼和state共同见证。abandon前两轮放弃有效，但“我也爱看云”仍是A22旧缺口，不把结构绿当质量绿；已修A22需复用其后续证据而非再跑已过G05。全部旧尝试ledger附入，不抹除未知FACTS/PLAN失败或合并不同版本统计通过率。

有限补验：仅缺主题/措辞的guess-object、story-forest、adventure-sea、association-flying，复用既有case/VoicePeer harness，每例3轮独立批，最多21次文本模型请求/45秒/原单轮预算；每次max_tokens1400、无fallback/额外重试、首失败止，不一次烧完整组。全部四例理论<=84请求不是本次授权执行，root逐批判结果再决定下一例。关联性/规则生效/角色和轮换必须人工读实际ACK/state；不重复G02/G05，也不重跑已过月球/太空/跨玩法等。免费优先沿现1017/既有授权，额度未知不等于免费账单，不能新增付费后备。

N02：新增一个不同于90来源/私事canary的并存边界：同Session从孩子来源建立角色、禁止传送规则、钥匙线索、情节先后、否定偏好；实际ACK带角色规则的玩法状态与关键情节；真实compact移除背景后录入新钥匙位置，query投影同时含旧精确证据与新事实，current game角色/规则不变，旧snapshot不能覆盖新来源。生产Session.send/ack/compact/query真实执行，script不改容量/TTL/上限。旧来源是evidence_only，不伪称全部已成为“当前事实”；新旧线索都保留便于模型处理修正。两次模型使用对照尚未执行：相同最小追问，分别用完整与compact后的真实context调用严格provider.plan，人工比较旧否定/新位置/先后/角色，expected不送模型；最多2请求、无图/TTS/ASR，只能证明这对合成上下文使用，非长聊泛化。计划表总上限86（84+2），不能视为批量执行许可。

N06：生产configured_feedback任务真实运行，注入一次固定storage异常，证明disabled且context退出报错，不能静默健康；原临时库关闭再重启后恢复，真实管理员store.maintain回复保留原delete_by，等值sweep后无单，再次重启withdraw仍copies=false。另一个真实临时TLS实例发送分片上传，中途取消/断连，等receiver释放后新认证连接withdraw，迟到完整submit被deleted拒绝，服务/库重开后重放仍deleted，库无canary正文。属于服务端上传中断后撤回，不冒称验证Android上传按钮并发，单active连接协议本来不支持跨连接并行写入。旧store/TLS方法已证明部分不重跑全集。

初次3项2PASS/1ERROR原件initial-clock-failure.log保留：模拟到delete_by后用真实旧时间重启触发持久clock回拨防护（storage）。修正fixture只在重启保持同一受控时间，未改宿主时钟/产品防回拨。最终local.log三项PASS、0SKIP。没有生产缺陷被证明，不为产PR修改产品。copies=false说明范围只到canonical临时库，未验证外部备份/历史journal/syslog/导出或供应商删除，绝不all-copies；A29-A31端到端设备/外部副本范围继续OPEN。
