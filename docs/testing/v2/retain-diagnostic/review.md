固定source79ba62b3b7e8b16d15b43249039891e568de8672的独立合成诊断/验收工具；不会先在未修生产上随机多跑一轮。依赖review分离修复，不改变在服ffd1dd9b。复用52e9add已审两轮driver（只更新pin）；新v2_retain_diagnostic.py仅观察这一个固定新建合成case的model调用，不能给任意输入/用户Session/历史文件路径，fixed_profile核源码和完整固定两输入。没有其它case/all/memory入口。

root审后唯一两轮命令（新目录、保留旧FAIL不覆盖）：
```sh
python3 -I -B scripts/v2_retain_diagnostic.py --case retain-only-change --execute --acknowledge-quota-not-live-verified --output /home/ubuntu/tech/v2-delivery/retain-quality-review-79ba62b3-once
```
真实生产VoicePeer/Session/PLAN/FACTS/review、安全字面guard、原ACK和BatchState清理，文本固定合成、TTS本地PCM、ACK合成。仅既有1017文本网络；16总请求/45秒/55秒父/max_tokens1400/HTTP10秒，生产原共享read retry/CAS/response预算保持；质量失败不新增请求，不自动重规划/额外循环/继续其它组，无fallback/precheck。默认不读凭据/执行云，不请求用户再核实时免费；执行ack只承认额度未知、既有授权，账户历史控制不是零账单证明。

TraceModel只包装原complete并原样返回结果，不改候选/审核值/ACK/Session，不调用模型作自评。保存有界新合成候选PLAN字段（非原始exception/message）、每次whole/segment候选与真实context、原模型返回allow/quality、固定safety_denied/quality_denied/allowed/invalid/upstream_failed分类；safety优先。旧单字段JSON记invalid/legacy_boolean_only，allow/quality记null，不把旧不明false猜成新质量或安全原因。原schema没有自由理由，raw_reason_available始终false。坏JSON/duplicate只记录invalid与hash，不落任意上游异常正文。instruction只存hash，headers/token/config/凭据不参与trace。source pin取固定生产HEAD既有backend/scripts/帮助文案，不递归新工具hash。

trace最多16记录，每份request快照<=65536 bytes、候选JSON<=32768 bytes；原driver仍总16请求（包括未记录正文的FACTS）、请求体/输出字符上限与外层进程监督不改。trace不保留PCM；结果中的实际文本/secret仅是这两个固定合成输入引发的当前新会话材料。两轮默认报告semantic_pass=null，diagnostic.complete_final_ack_for_all_turns及supervisor.all_target_replies_complete额外明确目标是否完整，不把artifact_valid或local_help当语义成功；partial prefix/failure/child cleanup/parent forced_exit各自保留。

测试：5项诊断+6项driver=11方法PASS（offline.log）。重现第二轮whole允许→首段允许并实际ACK→末段quality拒绝：whole context无前缀、后段context有前缀，只留实际已听不提交final state且无local_help。旧bool不补分类、任意外部输入拒绝且不调用inner、原异常canary不落盘、观察不增加成功组模型请求、默认disabled/pin。底层6项仍证两轮/16cap/失败停止/禁止all/生产format repair名额不被驱动取消。不等真实语义通过，root一次修复验收后再判，不扩memory或新局云。

本轮0云/设备/部署/长测/锁。review-separation原650项8FAIL/1ERROR及中断日志留于依赖生产提交，修正fixture/已合format repair具体detail次数后47相关项PASS，无skip/弱化负控；不以工具11项PASS冲淡旧分母。当前普通quality失败仅有界普通故障反馈，不声称已解决合理不重复接话。
