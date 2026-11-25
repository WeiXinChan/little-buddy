# TITA-88 M10 独立安全与隐私检查

结论：**软件门控与材料核心可复现回归通过；M10整体验收不通过，R88-01待原作者修复，真实语义安全及图片/设备/供应商范围仍OPEN。** 未修改产品代码、阈值、TTL或安全oracle；没有设备、模拟器、云模型/TTS调用或真实儿童数据。

## 固定对象与范围

- 本轮独立checkout起点/远端main：`379045c50f0ea234f19401ba2b8c82fda75f0528`，tree `ce87295a45a023b2f4337ba954af720c05d5054f`。
- 包含要求的main `12aa7a84c23c48e114108fc6fbe9fa7852ce1801`（tree `b97a8757de117e2d87c235e479db767d593b2b29`）。PR43在2026-11-25 11:05:26Z已合入；平台链接表及本地merge提交均确认，故它属于本轮真实已合范围。
- PR42仍open/API26失败，固定候选 `9e1ca95b8958f0a1b97c1e18ef263d18ed624ce6` 未引入。未重跑其构建，未改作者工作树。
- 已读批准的v2-requirements、v2-acceptance、v2-technical-design及独立技术审查review-tita-93。范围为A20–A26/A31/A38的现有生产接线与可离线边界，不新增产品政策。
- 威胁模型：模型JSON/审核结果不可信；审核超时/故障；跨段漏审；私事、未播事实、旧异步结果泄漏；过期日志/草稿副本；撤权、撤回和恢复导致超期/越权。真实供应商和设备不以模拟oracle替代。

## 实测与分母

| 执行 | 正常结果 | 失败/跳过 | 证据 |
| --- | --- | --- | --- |
| `python3 -m unittest discover -s tests/v2 -v` | 82/82 | 0/0 | python.log；含新增7项以及既有私事、handoff、已播事实、超期、取消和TLS测试 |
| 定向运行最终test_m10.py | 7/7 | 0/0 | m10.log；为上行子集，不相加冒充分母 |
| `M10_REQUIRE_HELP=1 python3 -m unittest discover -s tests/v2 -p test_m10.py -v` | 7/8 | 1/0 | safety-help-failure.log；7项同上，1项需求反例失败，未标expectedFailure/skip |
| `scripts/with-build-lock python3 scripts/test-m09-core.py --out docs/testing/v2/m10/feedback.json` | 111/111 | 0/0 | feedback.log/json；实际Kotlin核心、真实临时文件，注入时钟/授权/Provider |
| `scripts/with-build-lock python3 scripts/v2-parent-tests.py` | 92/92 | 0/0 | parent.log；实际家长授权域/PIN/撤权/CAS/到期测试；未设置PARENT_ANDROID_JAR，未编译Android适配器 |

独立正常方法总计285项（82+111+92），285通过/0失败/0跳过；另1项未解决需求断言失败。定向重跑7项和需求探针内重跑7项均为既有子集，不重复计入285。两类负控属于82项内的方法。重型JVM编译全程使用同一heavy.lock，顺序执行，未运行Gradle/SDK构建。

M10定向7方法含14个确定性场景：正常虚构/拒绝危险成对2、整段拒绝1、后续段拒绝1、审核不可用/非法布尔/重复字段/缺字段4、关系/隐私/虚假通知字面保护4、两类负控2。正常场景不证明真实模型允许，危险场景不证明真实模型会拒绝。负控仅在本测试进程移除字面保护/绕过语义门，均观察到原本禁止的文本进入合成，2/2有效；不修改生产树。

HTTP使用httpx.MockTransport，但经过实际DashScopeModel → UnifiedProviders → VoicePeer → 合成调用/发送/ACK/Session提交；不是只测枚举或直接调用固定假model。PCM和播放头是合成软件观测，不是手机声学证据。已有合成文本含猫船长、月球、合成危险请求，未云采样。

## R88-01：审核服务不可用时丢失独立安全帮助（高，A21/A23）

生产调用：`backend/v2/live.py`装配DashScopeModel/UnifiedProviders/CompanionPolicy → `VoicePeer._respond` → `UnifiedProviders.safe`。注入审核HTTP503，待播候选是正常猫船长句子，本轮输入为既有“合成危险请求”。

复现命令为上表`M10_REQUIRE_HELP=1`。实际结果：无未审核语音进入TTS（正确）；事件仅bound、revoke、`failure(code=voice)`，安全失败被通用语音故障吞并。`VoicePeer._respond`在stage=safety捕获异常后仅interrupt/send failure；`VoiceClient.kt`的failure分支只interrupt/status；`V2VoiceActivity.kt`的startVoice又把status回调接为空函数。没有独立本地安全帮助播放/提示路径。该断言只检查客户端可区分安全故障的必要信号，最终方案不限定新增事件名；独立安全帮助仍需作者实际接线验证。

影响：未经检查的输出确实未放行，但无法满足技术设计“保留本地安全帮助提示”和A23的求助通道要求。不能据此断言已经向真实儿童播放了危险内容，也不能声称本轮验证真实求助语义。

交接责任：M05/M04原作者定位安全故障分类及独立、预审、无需同一失败云链路的帮助路径，M06原作者接客户端实际呈现/播放；协调方安排原作者修复及非作者复核。需保留本失败原件，补503/超时/拒绝结果、求助输入、后台/取消/迟到、不得复播旧内容等定向证据。不得用放行旧文本或再次调用同一故障模型凑通过。

## 覆盖与真实未测边界

| 验收 | 实际生产位置及本轮证据 | 尚未通过范围/责任 |
| --- | --- | --- |
| A20 正常/危险 | companion.SYSTEM/safe/segment、VoicePeer的整段与逐句审核；成对接线及2负控 | 身体/死亡/情绪、自伤/伤人、虚构外衣、适龄质量、漏拦/过拒均未接真实模型；M05/M10/M12 |
| A21 危险求助 | stage=safety故障反例；输入并无确定性危险/多人求助分类器 | R88-01；伤害者可能为家长、停止玩法/可信成年人等真实模型语义未测；M05/M04/M06 |
| A22 年龄/关系 | SYSTEM明确5–8岁和AI身份；4条字面防线进入生产路径测试 | 同义改写、排他/秘密依赖、假感知、真实身份索取效果未测；没有声纹推断验证；M05/M12 |
| A23 分段/图片/工具 | 整段不允许则首句不合成；后句拒绝不合成、不提交整套新玩法状态 | 图片生成/内容审查Provider未接；V2VoiceActivity的reveal/hide回调为空，ACK gate不等于真实图片展示通过；M07/M06。工具生产副作用完整路径未实现/未测 |
| A24 无正文日志 | DashScopeModel异常脱敏，HTTP503哨兵不出现在事件/last_failure；FeedbackCore.record只落盘枚举/有界数值 | V2部署swap/core/监控/供应商缓存与训练/备份未实测；只运行本地测试，无真实录音/聊天制品；M04/M09及部署责任方 |
| A25 私事/结束清理 | 既有M05/R99/session测试覆盖私事共享投影、handoff清空、旧回调及未播事实不提交 | 真实Android资源释放、图片副本和供应商任务清理未测；M03/M04/M06/M07 |
| A26 日志7天 | feedback 111项包括实际核心日志期限/选中草稿副本/后台扫描/锁所有权 | 真实Android Job调度/可信时钟设备绑定、部署进程重启和真实经过7天未测；M09 |
| A31 材料最小化/授权/撤回 | FeedbackCore预览摘要、确认修订、授权提交、较早截止；111项含撤权竞争/删除失败/旧快照/副本与源日志分离 | 真实Provider默认拒绝；远程工单、维护者下载、所有副本/备份物理删除未验证；D02/D06/M09 |
| A38 交付真实性 | 本轮仅代码/合成测试日志/哈希；无人过程测试任务，未采儿童材料 | 没有儿童效果、整机或最终体验通过结论；完整发布审查属于M13/M14 |

本轮不要求用户操作，所有OPEN保留对应实际实现/部署责任，不把本地软件通过转交用户过程补测。PR仅交测试和证据，root审合；不自行合并。
