## 已知实测与尚缺证据

root在4ee87ea相同真实Qwen入口确认首轮通过，第二轮quality_whole、零音频；该源码未上线。现有日志共6次文本、1次TTS，第二轮PLAN/FACTS/whole各一次，plan_format_repair=null。本次失败不在锚点修复。它只证明安全允许、质量拒绝；没有保存当时第二轮候选、隐藏答案与完整审核输入，不能认定是正确确认误拒、错误候选被合理拒绝或其他规则不一致。用户“长耳朵后答兔子无反应”不能证明模型当时的隐藏谜底一定是兔子。

## 可证的输入契约缺口与最小补强

旧VoicePeer.review的query只作为Session.context的检索参数，未独立传给审核者。正常情况下record_input已经把本轮输入追加到recent，已有unrevealed/game/heard，所以不能笼统说续题审核没有谜底或当前输入完全丢失。但审核者必须自行判断哪条recent是当前猜测；recent受容量约束，不能作为本轮输入的唯一定位机制。原猜谜提示允许确认猜中，但没有明确确认本身已满足本轮、无需再给线索。

本补丁仅在已有猜谜或新开局pending_guess存在时发送独立current_input与review_phase，值来自当前Operation持有的同一query/phase。临时_review_turn在provider中严格验证并移出context，不写游戏/记忆/日志，不修改review响应schema。whole与segment都重新检查当前Operation并重新投影权威历史；本轮输入不是已播证据，也不是权限或指令。直接provider调用未提供envelope时仍走原契约。

提示对照原谜底、当前输入及已播线索：明确猜中可以确认，不强迫再提示/重述规则/另开题；猜错或含否定/引用/未定多候选不能强制判对，不能仅因包含答案字面确认。错误提示和假确认仍quality拒绝，未猜中泄底或其他安全问题仍allow=false。独立输入和固定提示会增加猜谜审核的请求token，实际费用/额度未知，不宣称零成本。普通聊天审核不增加此envelope。产品没有本地字符串判题器，没有质量拒绝续题retry，没有额外供应商调用或延长原预算。保留先完整审核、后分段审核、真实ACK才入heard/state。既有pending_guess与format repair不改。

## 离线验证

```sh
scripts/with-build-lock python3 -B -m unittest tests.v2.test_guess_review_turn tests.v2.test_initial_guess_quality tests.v2.test_guess_consistency
```

真实VoicePeer、生产Qwen HTTP adapter、模拟ACK：首轮长耳朵并确认提交兔子谜底，第二轮明确猜兔子→正确确认无需新线索；whole/segment均携带同一本轮输入且没有候选冒充已播。主动清除recent的受控投影仍携带当前输入，证明不依赖recent定位。另覆盖猜错后的正确提示、错误否认、假确认、否定/多候选/注入、提前泄底、不ACK不提交、畸形envelope请求前失败。受控审核器是有限合成对照表，只证明契约和失败关闭，不证明Qwen自然语言判断或现场根因。

## 真实release验收仍由root执行

保持在线0d42f0f不变。本分支基于未上线4ee87ea，root审核/CI后先用相同入口与当前Qwen配置验证：固定合成长耳朵/兔子首轮实际提交成功，再以明确兔子猜测验证确认；不能从任意随机首轮答案直接断言兔子必为正确。保留原请求/费用上限，失败即停，不重试采样到成功。另用已存在的固定guess-animal三轮case验证原失败入口，不把一次成功当确定性保证。

若再次quality_whole，root可在既有合成入口内存检查完整候选/原谜底/当前输入与whole或segment归属，先判断合理拒绝还是误拒；不采集用户音频/转写，不新增一次review求解释。输出仅固定元数据与通过/拒绝类别，秘密及候选正文不入交付日志。真机无反应对应哪个服务端候选仍待同机scope匹配。
