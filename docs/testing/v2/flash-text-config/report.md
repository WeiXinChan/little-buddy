## 显式V2文本候选与独立视觉审核

基线main4f991de1e2f18eb3f79db03ee1b217a6d4daa0db，另PR交付；PR95 FACTS预取保持独立，未复制/覆盖其提交。作者本批0云、无真实secret/config读取、无设备/部署/合并。

### 原始比较及剩余效果门槛

root三份flash-compare原metadata逐字保留：1017三轮必要结构/交付检查通过，首传输音频4498.98/3510.13/4991.58ms；未定版DeepSeek Flash为3518.43/3275.11/3813.62ms，但第3轮规则terms失败；omni首轮4905.76ms、第2轮无交付。不能忽略失败分母、把terms通过当充分语义评分，或将3样本/模拟ACK当P12分布/手机有效可听验证。

默认选1017符合最新用户指令；实际语义/审核更多用例与配置切换由root继续有界执行。历史403不代表当前权限，当前成功小样本也不证明所有功能/额度/长期可用。截图999.07K且用完即停只是用户提供账户状态，不是本地配置可证明的免费余额或零账单。

### 配置与模型角色

backend/v2/models.py分开TEXT_MODEL（默认deepseek-v4.1-flash-1017）/TEXT_MODELS（仅该快照、deepseek-v4.1-flash、qwen4-max）与IMAGE_REVIEW_MODEL（固定qwen4-max）。候选是管理员显式选择集合，绝不按失败自动遍历，qwen4不能成为Flash额度用尽后的自动付费回退。omni因本次无交付且未完成接口/效果验证不进生产白名单；不是宣称永远不能支持。

runtime.settings、DashScopeModel构造、preflight与probe均检查精确白名单；未知/空/错误类型/旧qwen3.8拒绝，不根据key猜权限。DASHSCOPE_LLM_MODEL仍是必须显式配置的一行；新安装example与发行默认1017，但现有显式qwen4不会被代码静默改写。root实际切换时只改受控V2文本字段，原image.json/review key/qwen4图审不随文本变化。

DashScopeModel每个请求仍stream=false、enable_thinking=false、max_tokens1400。仅SCHEMA_MODELS={'qwen4-max'}沿用已有json_schema；DeepSeek均json_object，并始终通过本地object_json/PLAN/FACTS/SAFE完整字段/类型/长度/来源/枚举检查。没有宣称供应商支持JSON Schema，也不跳过审核/放宽响应边界。PLAN/FACTS/文本SAFE/COMPACT/ENDPOINT使用同一显式文本模型；视觉prompt及图片审核固定独立qwen4、原nonce/hash/策略和安全生命周期不变。

### 正式入口核查的必要修正

核到serve_checked仍直接使用通用DashScope，PR93实际仅接runtime.providers：真实driver验证过的V2关闭适配并不自动覆盖正式service入口。现将正式live装配也切到同一V2Speech；新增无监听装配反例断言该实例、文本model和model.speech一致。原V1通用类、已审V2关闭算法和VoicePeer .5s预算均不改。不能声称此前私有部署一定已获得专用关闭语义；由root用本次最终包重新核实际正式路径。

### Usage及身份材料

没有usage收据的失败/取消请求计入usage_missing，不把0个已观察token当成实际0计费；harness单例delta在失败/取消时保守null，monetary仍None。成功已知/缺失、403免费用尽、取消/故障路径均检查，未采供应商真实账单。

runtime检查报告同时列实际models.llm及model_policy默认/精确允许集合/独立图审/JSON格式/nonthinking/无自动fallback/账户额度未证明。release-manifest.json同样包含默认models与policy，verify拒绝角色身份被改；package拒绝用当前新model身份标注不同models.py旧源码。测试真实从固定源码SHA打包/解包verify、改图审身份被拒；历史artifact要用自身受审版本验证/回滚，不给新格式伪造旧证据。source_sha/inventory/包hash仍非签名或家庭归属证明。

model-policy.json是声明快照；selected-1017-preflight.json是临时合成配置的真实离线prepare，socket.connect已禁用；另存explicit-qwen4-temporary-preflight表明显式配置可与默认不同。测试会生成的历史temporary-preflight已还原，不覆盖原证据。runbook和env模板已更新，协议/设备scope/APK未更改。

### 离线验证及范围

9新增方法：真实HTTP适配器＋actualVoicePeer三轮（所有调用1017/json_object/nonthinking、真实Session ACK推进、事实及usage）；非法mode/rules/roles/anchors、伪造FACTS、审核拒绝/重复JSON均0TTS/无交付；free-only403不改模型、不paid fallback、usage未知；精确白名单及probe；同HTTP记录prompt/PNG两次图审始终qwen4；实际preflight三候选/拒omni；正式live入口V2构造；发行角色身份/旧源码不匹配拒绝。

这些合成响应检查契约/失败关闭，不证明DeepSeek能理解所有规则或充分语义安全；actual效果/对话/私事/审核压测仍归root。相关原M05/M10/safety/metrics/image/release/deploy/probe/cleanup/本地speech回归通过，最终方法数/原始日志见result.json；无后端全集/CI/设备重复跑。旧测试的fake/legacy模型ID改为明确允许的合成1017，R88原归档源码/断言不改，仅在其fixture端注入允许模型继续验证原负控，不放宽生产白名单。

### root最小后续步骤（作者未执行）

独立QA后，将此配置PR与独立PR95按固定SHA组合，完整verify/preflight；在保留用完即停的账户条件下，以相同VoicePeer案例补玩法/规则互换/私事/安全及用量的有限真实效果检查。通过后root按现部署流程选择DASHSCOPE_LLM_MODEL=deepseek-v4.1-flash-1017；image review保持qwen4-max，V1不动。P12/P15/full_acceptance仍OPEN，免费额度不当永久成本证据，无自动fallback。
