## 管理挂起/同会话退出与可达路由交付

显式依赖PR49固定6ecb1afe5abcbc5fb866ff576e2d35ca5655bb80，隔离分支agent/tita-87-management；不改host/parent/VoiceClient/Activity、Android或反馈树。批准依据R14“原会话仍按期限保留，退出回待唤醒，不自动续播旧话”，并结合R07/R08/R13/R16。协议先交b30；最终字段及生命周期以同提交management-v1.md为准。

Session新增管理暂停独立状态；VoicePeer控制scope/pause/resume真实落地，不复用噪声suspend。入管理原子撤销媒体output并变更epoch/revision，清PCM/分析/等待决定，旧operation即便吞取消也不能后续调facts/审核/TTS或投递。按既有有界资源取消，然后发revoke与paused回执。receipt绑定Session对象/连接/会话/turn/output/epoch/revision；不是PIN或Grant，退出不恢复配置权限。正常退出仅回waiting_wake，待真实wake才接受儿童输入，绝不发open/续播旧段。首次尚未open可查询scope，不调模型/延TTL。

idle TTL/lease、输出/取消阈值均未抬高。管理heartbeat仅维持原lease，不能续idle TTL；期限等值清空，断线run.finally清会话/receipt；换人、interrupt撤销、连接代际变更和旧操作均不可复活。管理期与退出待唤醒期的PCM在解码前丢弃，不上传；后端不识别管理退出口令，客户端只本地专用检测，由b30负责。

本次部分告别暂停反例暴露已有资源close竞争：取消刚好碰到已成功关闭资源也被误判quarantined。修复为确认同一个close task成功后仍传播原取消；无法确认/失败继续quarantine。只使用原0.5s close截止的剩余时间，不新增窗口或放宽阈值。未确认provider取消仍不得恢复。

## 逐项路由核对（源码核对与合成夹具，不冒充模型质量）

| 范围 | 实际后端路径与本轮处理 | 边界 |
| --- | --- | --- |
| M04新请求/停播/噪声恢复 | advance→probe→seal→decision→stop→open→bind→audio→ACK；管理暂停独立屏障，不能resume_noise绕过 | 真实收音/声学仍最终集中验收 |
| 普通对话/四玩法 | UnifiedProviders严格plan五mode，VoicePeer统一审核/合成/ACK；保留已有规则/角色 | 本轮不重复全模式全集；不是新云质量证明 |
| 玩法退出/单人退出 | leave经完整ACK提交chat；共同会话一人退出用continue | 无声纹/身份认证，模糊意图由模型澄清 |
| 明确告别/全体结束 | 发现无end action漏接；补plan end，简短告别完整ACK后clear→revoke→session_end | 未完整播放或管理抢占不提早结束；客户端回待唤醒后新连接 |
| 单独换人/私事 | 原handoff清旧Session，private与shared投影分离；本轮定向复查实际跨玩法/私事/换人路径 | 不把管理音频输入为private儿童事实 |
| 图片/工具 | PR47准备与语音并行、完整ACK揭晓、hide/取消；管理撤销真实准备任务及迟到投递 | 动态Provider仍明确default回退；不虚构生成/任意工具 |
| 记忆 | PR48冷热证据/来源检索保持；管理保留已提交事实/未揭谜底，暂停拒绝新事实/压缩写回；断线清空 | 有限记忆覆盖声明保持，不承诺String覆写 |
| 管理取消/退出 | 新scope→management_pause→management_resume→waiting_wake→真实wake→新媒体代际 | host当前操作代际/Grant清理/本地检测唯一由b30装配 |

## 最小验证

17执行/17通过/0跳过：新增15（正常14、旧receipt越权恢复负控1），原资源失败隔离和跨玩法/私事/换人路径抽查2。原始tests.log；子场景不增加分母。覆盖首次未开儿童轮次、scope、完整恢复后真实新请求、TTL/lease等值、错误scope/revision/receipt、重复退出、撤销/换人/断线、管理及待唤醒畸形PCM不解码、迟到模型/真实默认图读取、部分ACK、未提交谜底、未确认provider释放、明确结束和一人退出边界。供应商语言/审核/PCM为明确注入合成夹具，本地PNG真实读；没有新云调用。

Python编译与diff检查通过；不重跑82/111/92等全套，不占heavy.lock/手机/模拟器、不部署收费或改V1。真实动态Provider、反馈平台删除、专属端点/V2权限缺口仍集中PR45 resources.md，未假删除。Android装配、真机、声学、跨功能长稳留最终集中验收，作者不自行合并。
