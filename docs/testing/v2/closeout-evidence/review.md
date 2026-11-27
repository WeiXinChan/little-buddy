本批为 PR131 固定 67ac8405 的独立 worktree，只补离线证据，不改原冻结分支/产品/在途进程/锁。

依据：QA v2-closeout-review/audit.json，哈希见index.json。A12既有test_m05同Session160轮>64KiB输入输出且走生产压缩与ACK；memory_growth已有冷热归档/短主题否定/来源原子性/未播边界。A33既有private_replan公共投影、handoff/end/失败保持私事。A10既有fact_prefetch迟到epoch/revision/吞取消隔离，M04旧epoch wire拒绝。复用这些结果，不另造语义模型或长测。

新增3项：
1 同一个生产Session记录90个独立精确来源，实际形成冷归档；同Session完整ACK承诺、未ACK canary后interrupt，真实compact移除public背景，再检索完整否定与已播承诺，未播正文不得进入context，_fits成立，无修改容量/TTL。
2 实际VoicePeer+UnifiedProviders+合成model，经private回应→公共guess重规划→story切换：核同Session、第二PLAN公共投影不含私事canary、shared不含隐藏答案；unrevealed专用内部通道仍有答案且不在heard，换题后清理。内部模型需要隐藏答案用于玩法，此检查不错误宣称所有内部上下文均无答案；生产安全审核仍是防模型泄露的一道门，脚本模型不证明真实语义抗泄露。
3 明确合成PLAN continue保持共同Session→真实handle(stop)换epoch使旧ACK失效且不结束Session→合成PLAN end告别完整ACK后清空。意图分类是注入，不证明真实ASR/LLM能识别谁退出；后端没有参与者注册表/声纹身份，角色列表不是认证的在线人数。现存提示要求“我先退出你们继续”continue、“我们都不玩了”end。是否实际遵循需真实文本/语音另验，不能用此报告关闭完整A34。

本轮日志：new.log初次13PASS含意外被unittest发现的既有Integration十项（均真实执行含160轮压缩，无网络云/服务）。将导入改为模块引用后targeted.log仅11项PASS（新增3+旧epoch/revision取消3+private_replan5），old-epoch.log独立1PASS。共25次执行、22不同方法，0FAIL/0SKIP；不把重复3项计新覆盖。没有发现本范围生产缺陷，故只提交测试/说明，不修改产品。后端内存状态/ACK不代表声学播放、真实语义或设备多人行为。A12/A33逻辑证据加强，完整体验验收仍OPEN；A36长测由QA另行收集，本批不引用其未完成结果。
