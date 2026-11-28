## 已确认的第三轮故障

root独立全真Qwen、无预塞PLAN的合成三轮：1d778cb第一轮长耳短尾题54 ACK，第二轮明确答兔子获得正确确认及再玩邀请44 ACK；第三轮明确请求新动物谜语后plan_guess_answer_changed、0 ACK。没有重复供应商调用来采成功样本。

该固定错误在源码唯一触发条件是：action=continue，原game.mode=guess、已有unrevealed，新的mode=guess且secrets非空、与原答案不同。因此是模型把新题错误编码成同题继续，本地同题换底守卫正确拒绝；不能删除守卫、把continue自动改change、强转秘密或丢弃新线索。前两轮的实际成功证据属于1d778cb，不能冒称它已验证后续冻结版或第三轮修复。

## 最小候选修复：语义显式，替换提议独立审核

planner与reviewer共有猜谜契约明确：明确要求再出新题/换题属于同玩法内新开题，须action=change、mode=guess、guess_role=setter；continue始终保留原谜底，即使上一轮已猜对。否定/引用“换题”、猜测本身、原题提示都不是授权。不给本地增加字符串判题或意图分类器，不把模型change本身当用户授权。

已有题目下，仅setter、action=change、非私密、无tools的候选可以投递独立pending_guess四字段；provider带pending_guess_kind=replacement，仍保留context.game/unrevealed/heard原值。审核必须依据独立current_input核实明确换题请求，再按新候选谜底核验新线索。新题审核不能要求线索描述旧谜底，也不能把pending当已提交。未授权换题、错误线索quality拒绝，提前泄露新答案或安全问题allow拒绝。未换题continue仍原路径，原plan_guess_answer_changed完全不改。

首次及每个分段仍完整审核，最后有效ACK才替换游戏/谜底；未ACK、被拒或取消保留原题。不开续题quality重试、不新增模型调用、不扩大15s或共享retry预算；若Qwen仍输出continue换底，继续失败关闭。请求增加少量pending元数据与固定提示token，实际费用/额度未知。保留原在线0d42不部署。

## 可复算离线验证

```sh
scripts/with-build-lock python3 -B -m unittest tests.v2.test_new_guess_round tests.v2.test_guess_review_turn tests.v2.test_initial_guess_quality tests.v2.test_guess_consistency
```

生产Qwen HTTP adapter + 真实VoicePeer + 模拟ACK：兔子线索→答对确认→明确新题→猫线索；审核时原题/已播历史未被改写，新题最终ACK才提交。多分段保持相同当前请求和独立新候选，原题保留到最后ACK；未ACK不替换。另测continue换底仍失败、未要求/否定/引用换题拒绝、错误新线索quality拒绝、泄底safety拒绝，无隐藏再生成。这是受控模型与有限语义表，不证明真实Qwen必定遵从新契约。

## root真实验收

不重复作者供应商调用。审查/CI后root沿同一无预塞PLAN入口、相同配置及原费用上限验证第三轮；必须查看三轮实际模型输出与ACK/game commit，不预塞新题成功或把无音当有效回答。如果第三轮仍continue换底，保留此固定错误停止，不能自动再试到成功。若change进入审核却拒绝，只在合成入口内存核验当前请求、候选与原秘密；不输出原始用户音频/转写/秘密。source升级与回滚均由root决定。
