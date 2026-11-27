本批基于 PR117 head 4a6ea62c867960a79cb3e6c355acd93b7309eb80，独立增量，不混 PR116/118。

已证原因：真实阳台输入在 facts 来源校验失败；失败发生于事实提交、审核和 TTS 之前。原 generic failure 只发 voice，没有固定 local_help。原始错误 value 未保存，不能推断人称/标点或具体改写导致该次错误。baseline.json 保留原报告哈希及实际失败；不重跑真实云。

修复：FACTS 提示明确逐字来源、人称标点与建议不属于输入事实。提供方与 Session 严格校验不变；非法事实不丢弃、不伪造、不提交。当前 scope 的 facts/fact_commit 错误经既有 revoke 和安全帮助控制路径降级为固定本地帮助，last_failure 原阶段/类型/契约保留。既有 review_unavailable 枚举表示必要安全上下文无法完成，不代表声称实际图审或文本审核 HTTP503。显式 quota 保持原语义，取消/过期/换 scope 不发提示；无新增模型调用或重试。

Android 仅改 LocalHelpOutput.TEXT：条件危险时先劝阻并呼叫能安全帮助的可信任成人，必要时安全寻求紧急帮助，不指示自行攀爬跨越或冒险移动。协议、离线 TTS 选择、生命周期/音量门禁不改。旧 APK 文案不会被后端更新；需 root 后续配对构建与真实验收，本批未编译 APK、未操作设备。

验证：新增9项（来源严格拒绝/原错误元数据/0TTS/私事/提交失败/撤销过期/额度/幻想正控/文案静态），原 facts diagnostics7、visible contract4、G02六，共26 PASS。受影响并行 FACTS14 PASS。初次并行集13PASS/1FAIL原件 prefetch.log 保留：安全帮助会换新 input_budget，旧断言读了新对象；现在在真实任务运行中保存原 budget 引用，仍断言共享 retry_revision=0 且总请求<=3，不放松预算。prefetch-fixed.log 为修后原14项结果。合计40个不同方法通过；非真实模型质量或声学证明。

仍未验证：真实来源错误是否不再出现、危险回复语义质量、固定帮助可听性/设备效果；完整 A21 未通过。没有云调用、secret/config 读取、部署或合并。
