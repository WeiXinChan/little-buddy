A12短中文主题检索与冷热/满容量回归

基线main4f0a75a92bca2e0433c7da5feb5404df0baf3bde。生产只改backend/v2/memory.py，不修改Session存储/上限、模型/提示词、VoicePeer、部署、凭据、Android或冻结APK。真实推理0，不调用当前403的DeepSeek，也无Qwen回退。

原失败证据保留

root提供的原全后端266方法日志原样复制为original-final-266.log：264通过、2失败，本轮没有重跑或覆盖它。两个旧方法在原head的独立运行亦原样保留original-targeted.log（2/2失败）。新增短查询断言在原生产代码运行original-short-query.log：2方法、7个子测试/断言失败。original-reproduction.json记录原hot5+cold38、猫/狗/猫狗/猫呢/狗呢找不到原始偏好/纠正，长片段喜欢猫或刚才说错了能找回的实际差异。不是数据丢失，而是排名缺少单字主题信号。

最小修复

保留ASCII词匹配（3分）、原相邻双字匹配（1分）。对剔除常见语气/功能字后含1–4个中文内容字符的短查询，加每个不同主题单字的精确包含匹配（1分）；例如猫、猫呢、猫和狗呢可提取猫/狗。语气/功能字只作用于query，绝不从source_text删除字或重写命题；纯语气双字不计分，纯语气查询走原空查询最近4条路径。语气字表及阈值在代码可审，不引入模型/分词库或语义推断。

cold预选与最终有界投影共用同一relevance计算，避免两个排名层口径不同。上限仍为有query时最多12条cold、投影18000字节、Session65536字节、源archive1048576字节；没有抬topK/容量。非匹配记录仍按原recency后备；不能把所有retrieved_sources都当语义强匹配。private过滤仍在打分/coverage前，played事实优先级/完整原文/遗漏提示保留。

固定fixture（完整span、无dimension）依次录入我喜欢猫、我喜欢蓝色、刚才说错了，我不喜欢猫，我喜欢狗，20条无fact背景，再40条不同我喜欢第N种颜色、逐条turn递增。当前仍hot5+cold38，共43个唯一source_id；每条原文/ID/完整记录与入库时捕获值一致。

| 查询 | 验证必须召回的完整证据 |
| --- | --- |
| 猫 / 猫呢 / 猫狗 / 猫、狗 / 猫和狗呢 | 原猫偏好 + 完整猫否定/狗纠正 |
| 狗 / 狗呢 | 完整猫否定/狗纠正，不截成单独肯定句 |
| 蓝色呢 | 原蓝色偏好，与动物偏好分开保存 |

同时用40条新颜色原文都带呢吧吗啊的反例确认语气字不会把这些无关来源排到旧主题证据前；纯语气query与空query的facts投影一致。否定、过去时、他人主语和疑问四种原命题逐条保持原文/ID与evidence_only；私事cold不出现在shared事实或coverage中。短query是词法启发式，不承诺一般中文指代/同义词/语义理解；同一句纠正作为完整来源返回，不生成合并结论。

两旧断言更新且加强

原“43条都在hot”断言改为hot+cold共43、source_id唯一/两区不交叉、全部原始记录精确相等，并按猫/蓝色query验证纠正和两类偏好可检索；不是只删除断言。所有来源均实际record_input不同完整原文产生，未塞固定facts或重用同一事实代证。

原期待BufferError的方法在默认65536上限先真实保存43条不同来源（包含cold），再构造仍fits但不足新fact保留预算的满容量状态。验证record_input返回False、facts/archive/public不变、memory_limited与coverage.capacity_limited为True、新输入留在有界recent、无伪保存fact，memory_revision按契约前进且仍fits。非法第二条来源使整批ValueError并保留所有状态，包括之前有效的第一条候选，不用容量False吞掉非法来源。

实测：fixed-targeted.log为12执行/12通过/0失败/错误/跳过（两旧项＋5个新短查询项＋5个直接受影响的增长/隐私/容量/非法来源/played检查，含500不同原文增长）。没有重跑旧266集合、构建APK或部署。checks.json与fixed-reproduction.json给出分母、原日志hash、实际5+38分布和逐query/coverage结果。原266的2失败仍作为历史记录保留；本轮12 PASS不冒称新全量266 PASS。

后续由root独立复核固定SHA、重冻结后端并安排其必要集中检查；本批不重做部署/凭据或派成员。
