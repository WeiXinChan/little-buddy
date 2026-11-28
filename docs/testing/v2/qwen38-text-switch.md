## V2 显式切换 Qwen3.8 Omni 文本

基于 main `12d1b1f`，保留线上 `d48025f01a2317619f0524f743bc577c46a98fe2` 的 timeout 诊断/stream ASR 接线及 main 已合入的服务恢复。只改 V2 text allowlist 与本模型请求/完整响应验证，不改 V1、ASR、TTS、图像审核、APK、wire、预算或上下文提交条件。

root 在独立 V2 service-env 中明确设定：

```dotenv
DASHSCOPE_LLM_MODEL=qwen3.8-omni-flash
```

runtime 必须显式提供全部配置；保留历史 `TEXT_MODEL` 只是旧 release 默认标识/兼容，不是回退。应检查离线 preflight 报告 `models.llm` 正是本模型，不能只看 default_text。所有候选仍只有显式配置入口，代码没有自动切回 DeepSeek、qwen4 或付费模型。

官方 https://help.aliyun.com/en/model-studio/qwen-omni 当前文档中 Qwen3.8 使用 `reasoning_effort=none` 关闭思考（不是旧 Qwen3 的 enable_thinking），支持 non-streaming/json_object 与 text modalities。当前适配固定 `modalities=[text]`、`reasoning_effort=none`、`stream=false`、1400 token；不发送音频/图像输入、搜索或工具请求。仍将 canonical JSON Schema 放入指令并严格本地验证；没有 json_schema 能力假设、输出修补或无审核播放。只有 finish_reason=stop 的非空纯文本响应才可进入原 JSON/PLAN/FACTS/REVIEW 校验；截断、工具调用、refusal 或非文本失败关闭。

## 用完即停与部署交接

“没有付费回退”由单模型请求和 quota 异常原路径保障。供应商是否扣费不能由 JSON 参数或模型名称证明；本补丁不虚构 free-only 请求字段。上线前 root 必须核对用户截图所对应的同一账号/地域/workspace/确切模型确实启用控制台「免费额度用完即停」，记录检查时间和非敏感证明；未确认则不发实际请求。额度余额、计费单位、单价、实际账单继续未知，不宣称免费。AllocationQuota.FreeTierOnly/insufficient_quota 发 quota，权限/网络错误失败关闭；无模型回退或 quota 重试。保留原有经审核的同模型只读契约修正预算，不扩大次数，不把 quota 当可修正结构错误。

root 执行既有部署程序：审核 PR/CI、冻结 source 并以该 source 打包验证，独立 V2 service-env 只改 LLM 行，运行现有 `backend.v2.live --check`（其余参数沿既有受保护配置），确认 `models.llm` 和无 fallback。按既有 V2 激活/健康检查流程部署；本次代理未写线上配置、重启、触碰手机或实际供应商调用。回滚优先停止新调用并恢复上一 source/配置；若 DeepSeek 仍额度耗尽，不自动拿它恢复服务，也不换收费模型。V1 和独立 image review 仍原配置。

## 验证事实与边界

root 已有的 availability 报告：本模型单次 text JSON HTTP200；另一个 `d48025f-plus-candidate` 报告4种合成 PLAN与逐段审核共8次，PLAN模式匹配，association 的审核拒绝（不能抹成通过）；无 FACTS 验证，不是本冻结补丁的全链路验收。更早 `4f991de1` 多轮第2轮 PLAN失败，仍保留为失败证据。不能用 mock 或旧样本证明当前模型语义/真机效果。

新增离线测试复用真实 DashScopeModel HTTP adapter、UnifiedProviders 和 VoicePeer/ACK pipeline：本模型的5类结构阶段、非法 PLAN/anchor、秘密谜底隔离、多轮 context commit、安全拒绝零TTS、事实原文来源、额度/权限/网络单次无回退、截断/工具/refusal/非文本拒绝；所有请求由 httpx.MockTransport 控制。既有整个 V2 回归仍需通过。

必要最小真实确认由 root 统一预算并在确认「用完即停」后执行：固定纯合成输入，经冻结适配器各1次 PLAN/FACTS/REVIEW（3次文本，ASR/TTS/image0、无重试）；使用真实本地校验器核对，事实需保留完整否定/主语，审核拒绝不能播。已有同一冻结 source 的等价证据可免重复；单次失败即停，不做矩阵，不宣称P95或童声效果。此处是交接建议，不是已执行或新增授权。

仓库根目录定向回归（2GB构建锁，串行，包含 Git 所需 process-local safe.directory）：

```sh
sudo -n scripts/with-build-lock env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0="$PWD" python3 -B -m unittest tests.v2.test_omni_text tests.v2.test_flash_text_config tests.v2.test_visible_model_contracts
```

PID12482 SERVER_TIMEOUT 与原code33第二 SERVERVOICE 根因仍 UNKNOWN；换模型不等于修复它们。
