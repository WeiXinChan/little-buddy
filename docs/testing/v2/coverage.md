# A01–A38 执行器覆盖表

所有产品状态均为NOT_RUN，尝试数0。已有工具指可复用双件/注入器与其自测，不能称完整产品执行器。当前真实产品适配器0个、端到端A执行器0个；38行是映射，不是38个已实现执行器。

|验收|需求|已有工具（仅夹具）|尚缺产品执行器/证据|负责接入|
|---|---|---|---|---|
|A01|R01 R02|仅场景定义，无专用执行器|产品适配器、真实观测及独立断言；自动启动、唤醒、结束及状态截图|TITA-84|
|A02|R02|Clock / FaultBudget / write_signal；dialogues.json|产品适配器、真实观测及独立断言；未唤醒环境音、单独唤醒、紧接意图；D03声学/实际输出证据|TITA-82|
|A03|R03|仅场景定义，无专用执行器|产品适配器、真实观测及独立断言；四类玩法分别多主题、多措辞、多轮执行|TITA-83|
|A04|R03 R08|仅场景定义，无专用执行器|产品适配器、真实观测及独立断言；猜谜转故事、交换出题、改规则、放弃|TITA-81、TITA-83|
|A05|R04|仅场景定义，无专用执行器|产品适配器、真实观测及独立断言；代理盲评候选声音和连续对话|TITA-90|
|A06|R05|Clock / FaultBudget / write_signal；dialogues.json|产品适配器、真实观测及独立断言；完整句、未完句、拖长音与明确思考的合成音频；D03声学/实际输出证据|TITA-82|
|A07|R05|Clock / FaultBudget / write_signal；dialogues.json|产品适配器、真实观测及独立断言；同一个“嗯/对”置于确认、故事附和、犹豫、纠正场景；D03声学/实际输出证据|TITA-82|
|A08|R06|Clock / FaultBudget / write_signal；dialogues.json|产品适配器、真实观测及独立断言；播报中“停/不/等等”、续说及重复机器人词；D03声学/实际输出证据|TITA-82|
|A09|R06|Clock / FaultBudget / write_signal；dialogues.json|产品适配器、真实观测及独立断言；可疑声先暂停、明确噪声、无法识别真实表达；D03声学/实际输出证据|TITA-82|
|A10|R06 R08|lab.Protocol / Clock / Playback；test_protocol_*、test_f03_*|产品适配器、真实观测及独立断言；取消后注入旧模型、音频、工具、图片和重复回执|TITA-81、TITA-89|
|A11|R07|lab.Protocol / Clock / Playback；test_protocol_*、test_f03_*|产品适配器、真实观测及独立断言；停播、结束玩法、告别、临时离开、过期及进程重启|TITA-81、TITA-89|
|A12|R08|lab.Protocol / Clock / Playback；test_protocol_*、test_f03_*|产品适配器、真实观测及独立断言；长对话压缩及角色/谜底/线索/情节断言|TITA-81、TITA-83|
|A13|R08 R09|lab.Protocol / Clock / Playback；test_protocol_*、test_f03_*|产品适配器、真实观测及独立断言；在谜底前、句中、句尾精确插话并观测画面；D03声学/实际输出证据|TITA-81、TITA-85|
|A14|R09|lab.Protocol / Clock / Playback；test_protocol_*、test_f03_*|产品适配器、真实观测及独立断言；请求配图、慢/失败、改话题、再看、延长、收起|TITA-84、TITA-85|
|A15|R10|仅场景定义，无专用执行器|产品适配器、真实观测及独立断言；固定素材清单、图像代理评审、目标屏幕截图|TITA-85|
|A16|R10|仅场景定义，无专用执行器|产品适配器、真实观测及独立断言；同角色跨场景、多次生成、孩子主动改配饰|TITA-85|
|A17|R11|Clock / FaultBudget / write_signal；dialogues.json|产品适配器、真实观测及独立断言；部分识别、完全失败、连续失败、语义歧义|TITA-82、TITA-89|
|A18|R11|Clock / FaultBudget / write_signal；dialogues.json|产品适配器、真实观测及独立断言；ASR/LLM/TTS 超时、断网、恢复、额度不足|TITA-82、TITA-89|
|A19|R11|lab.Protocol / Clock / Playback；test_protocol_*、test_f03_*|产品适配器、真实观测及独立断言；生成/合成/播放阶段故障，失败后结果晚到|TITA-82、TITA-89|
|A20|R12|checked_effect与安全故障负控；dialogues.json|产品适配器、真实观测及独立断言；正常身体/死亡/情绪问题与危险请求的成对样例|TITA-88|
|A21|R12 R16|checked_effect与安全故障负控；dialogues.json|产品适配器、真实观测及独立断言；即时危险、伤害者可能是家长、多人求助|TITA-88|
|A22|R04 R12|checked_effect与安全故障负控；dialogues.json|产品适配器、真实观测及独立断言；排他关系、秘密要求、假装亲历/感知、索要身份|TITA-88|
|A23|R12|checked_effect与安全故障负控；dialogues.json|产品适配器、真实观测及独立断言；安全服务故障及危险内容在分段/图片/工具中出现|TITA-85、TITA-88|
|A24|R13|Material / assert_no_body；test_f04_*、test_f05_*|产品适配器、真实观测及独立断言；检查文件、日志、异常、监控、缓存和崩溃路径|TITA-87、TITA-88|
|A25|R07 R13|lab.Protocol / Clock / Playback；test_protocol_*、test_f03_*|产品适配器、真实观测及独立断言；正常结束、断线、异常退出及过期清理|TITA-81、TITA-88|
|A26|R13|Material / assert_no_body；test_f04_*、test_f05_*|产品适配器、真实观测及独立断言；可控时钟推进至 7 天边界，清理任务失败/恢复|TITA-87、TITA-88|
|A27|R14|Management；test_f01_*、test_f02_*|产品适配器、真实观测及独立断言；多种语音进入表达、错误 PIN、取消、退出及闲置|TITA-86|
|A28|R14|Management；test_f01_*、test_f02_*|产品适配器、真实观测及独立断言；管理中说话、旧语音/图片返回、清理及恢复 PIN|TITA-86|
|A29|R15|Material / assert_no_body；test_f04_*、test_f05_*|产品适配器、真实观测及独立断言；无日志/有选定日志提交，离线、失败、回复查看|TITA-87|
|A30|R15|Material / assert_no_body；test_f04_*、test_f05_*|产品适配器、真实观测及独立断言；草稿/上传中/已提交时撤回、离线删除与重复请求|TITA-87|
|A31|R15|Material / assert_no_body；test_f04_*、test_f05_*|产品适配器、真实观测及独立断言；可控时钟验证 24 小时及原单 7 天，补充/回复|TITA-87、TITA-88|
|A32|R16|Clock / FaultBudget / write_signal；dialogues.json|产品适配器、真实观测及独立断言；双人轮流、混音重叠、冲突意见和三人边界；D03声学/实际输出证据|TITA-89|
|A33|R16 R08|lab.Protocol / Clock / Playback；test_protocol_*、test_f03_*|产品适配器、真实观测及独立断言；角色交换、加入、单独交接、私人聊转共同故事|TITA-81、TITA-89|
|A34|R16 R14|Management；test_f01_*、test_f02_*|产品适配器、真实观测及独立断言；一人退出、全体结束、自称家长、任何人喊停|TITA-86、TITA-89|
|A35|R17|仅场景定义，无专用执行器|产品适配器、真实观测及独立断言；真实服务候选在同一合成场景比较；D03声学/实际输出证据|TITA-90|
|A36|R17 R18|仅场景定义，无专用执行器|产品适配器、真实观测及独立断言；60 分钟混合互动，网络扰动、反复打断和换玩法；D03声学/实际输出证据|TITA-89、TITA-90|
|A37|R18|仅场景定义，无专用执行器|产品适配器、真实观测及独立断言；发布配置安装/升级、权限、锁屏后台及重新前台|TITA-91|
|A38|R13 R18|evidence验证器及run自测报告|产品适配器、真实观测及独立断言；检查报告、制品与所有任务清单|TITA-79、TITA-88、TITA-91|

A01/A03–A05/A15–A16/A35–A37当前只有批准场景和证据模板，UI/视觉/模型/供应商/长时/发布执行器待后续阶段实现。A06–A09工程音调不能替代语音，A20–A22自造对话标签不能替代安全模型评测。A29–A31内存删除双件不能替代真实平台副本删除。

接入流程：后续任务提供适配器，把合成事件送入隔离产品并返回观测；通过evidence.execute执行确定性oracle，再经validate_product_result约束报告，独立评审源观测与来源。任何缺适配器/空观测/错误实现/运行异常都失败，不得给默认成功。设备/声学与代理视觉语言评审的采集器本轮未实现。
