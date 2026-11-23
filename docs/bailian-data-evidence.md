# 百炼北京语音链路数据处理证据

核验日期为 2026-11-24（北京时间），核对人为瓦力·设计开发（TITA-71）。范围为中国站华北 2（北京）家庭 V1 标准模型 API。接口、模型与业务空间地域依据既有合成试验和成人验证记录，代码依据 `b198a7266835b0cfbd2db345ab88dd2cfea6e105`，SSH APK 路径另核 PR #26 的 `37d158a21164da20f113f804b825dbbd134ea602`。各模型使用别名，实际服务端快照及正式账号设置待证。本次仅查公开资料、源码、已有工程记录和服务器配置元数据。 [既有试验记录](cloud-voice-validation.md)

## 官方通用证据（均于 2026-11-24 查阅）

- **G1 中国站百炼服务协议 §6.2.3–6.2.9、§8.4（公开版本自 2026-09-02 生效）。** §6.2.3 允许阿里云或获授权合作伙伴按协议和有记录的指令处理客户业务数据，亦允许为落实法律要求（如内容安全过滤）或遵照主管部门指示处理。§6.2.4 约定按客户删除指令处理。§6.2.5 的最短必要留存和未经授权不得用于供应商模型训练的约束指向对话数据。公开条款没有逐项界定原音、转写、合成音频、错误样本是否均属该范围，也没有确认各接口的人审边界。法律和安全技术限制可能延迟备份删除，届时限制后续处理。终止、到期或欠费后的缓冲期取决于适用专有条款，另有法定、主管部门或约定例外。协议约定在所选服务和模型所在国家或地区处理，允许在合规条件下调度临时资源。保密条款另列依法披露等例外。未说明三接口的逐请求删除方法、内部副本分布或具体期限。§5.2.2 对 Token Plan 个人版及 Coding Plan 另有改进及模型优化授权。本矩阵范围为标准模型 API。 [百炼服务协议](https://terms.alicdn.com/legal-agreement/terms/common_platform_service/20230728213935489/20230728213935489.html)
- **G2 中国站 FAQ 和隐私说明。** 中国站通用说明指明模型及应用调用产生的数据依法存储，并说明用户数据不用于模型训练。FAQ 所述体验中心历史对话及报错记录规则适用于控制台体验。删除 API Key 可阻止后续调用，历史记录是否清除需单独核实。 [FAQ](https://help.aliyun.com/zh/model-studio/faq-about-alibaba-cloud-model-studio) · [隐私说明，2026-10-10 更新](https://help.aliyun.com/zh/model-studio/privacy-notice)
- **G3 审计与推理日志。** 平台审计日志默认开启，记请求 ID、时间、模型、用量、状态、延迟、错误码等元数据，详情可含错误信息，字段设计不含 Prompt/Response。默认查询窗口 7 天，最长查询窗口 30 天，实际存储 TTL、平台逐条删除与销毁周期未公布。北京的推理日志默认关闭，另行开启前需启用审计日志投递、授权服务角色并配置自有 SLS 日志库。支持的模型可将正文请求、响应及中间步骤投递到该库。客户授权后可将推理日志回流为独立训练数据集。关闭投递影响未来数据，历史 SLS 副本按 G4 处理，已导入训练集另由数据集管理处理。平台日志、SLS 日志与数据集分别核对适用的删除入口、权限和副本。运维管理 → 模型监控 → 模型详情 → 日志是查看入口。监控及投递能力依模型而异，部分语音模型受限。 [监控告警](https://help.aliyun.com/zh/model-studio/model-telemetry/) · [模型数据](https://help.aliyun.com/zh/model-studio/training-set-and-evaluation-set/)
- **G4 自有 SLS 副本。** 已投递副本受该库保存时间约束。公开范围为 1–3650 天，3650 表示永久。指定记录软删除需要支持该能力的 Logstore 与相应 RAM 操作权限，逻辑删除后底层数据依 TTL 或后台合并清理。配置入口为日志服务目标日志库，整库删除、TTL 修改及日志软删除各有权限。下游投递副本需单独处理。现有北京账号是否开启投递及其日志库、TTL、RAM 授权和下游副本未核实。 [管理 LogStore](https://help.aliyun.com/zh/sls/manage-a-logstore/) · [修改与删除日志数据](https://help.aliyun.com/zh/sls/modifying-and-deleting-log-data) · [百炼 RAM 权限](https://help.aliyun.com/zh/model-studio/bailian-ram-permission)
- **G5 内容安全与工单。** 公开资料说明百炼有内容安全检测，并支持业务空间启用额外安全护栏。故障排查文档建议提交 Request ID 和脱敏材料。三接口的人工审核触发、可访问角色、抽样、错误样本及工单附件的期限和删除权限未找到公开专属证据。 [输入输出 AI 安全护栏](https://help.aliyun.com/zh/model-studio/content-security/) · [错误码](https://help.aliyun.com/zh/model-studio/error-code)
- **G6 国际站范围。** 国际站说明（2026-11-17 更新）列出其标准推理输入输出的 30 天规则及例外。其 ZDR 适用国际站企业客户、非中国大陆地域、启用的业务空间和所列模型。名单含 `qwen3.8-flash`，语音条目为指定 Qwen Audio 系列。国际站的期限、ZDR、人审及缓存规则均无北京适用证据。 [国际站数据留存](https://www.alibabacloud.com/help/en/model-studio/data-retention-policy)

## 逐 API / 数据项矩阵

表中证据为 2026-11-24 查阅的中国站公开资料。每条内容记录的期限、删除和人审按对应行判定。

| 北京模型与接入 | 数据与用途 | 已证实的适用证据 | 期限、删除和访问待证 |
| --- | --- | --- | --- |
| `fun-asr-realtime`，双向 WSS `/api-ws/v1/inference` | 原始语音 PCM，当前轮识别 | 北京接口说明确认收二进制音频。G1/G2 提供平台通用处理和训练约束。 [Fun-ASR WebSocket](https://help.aliyun.com/zh/model-studio/fun-asr-realtime-websocket-api) | 原音是否落盘、缓存和备份期限、按任务删除入口及权限、人审触发和角色未知。 |
| 同上 | 中间/最终转写，项目消费最终句 | API 说明返回识别事件及文本。G1/G2 适用平台通用层。 [Fun-ASR WebSocket](https://help.aliyun.com/zh/model-studio/fun-asr-realtime-websocket-api) | 中间与最终结果各自的 TTL、按任务删除和权限、人审核验未知。结束或关闭流只代表结束处理通道。 |
| `qwen3.8-flash`，HTTPS `/compatible-mode/v1/chat/completions` SSE | 请求文本，包括系统指令、当前转写与有界会话上下文 | 模型页列北京，Chat Completions 参考记录请求与流式格式。G1/G2 说明通用对话数据政策，具体请求字段是否落入该条及账号其他授权待证。若启用且模型受支持，G3/G4 另有正文副本。 [模型，2026-10-29 更新](https://help.aliyun.com/zh/model-studio/qwen3-8-flash) · [Chat Completions](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions) | 平台内容及缓存/备份的具体期限、删除接口或有权角色、账号投递与缓存配置、人审范围未知。 |
| 同上 | 请求公共前缀，上下文缓存 | 北京模型清单含该模型。隐式缓存自动启用、不可关闭，公共前缀达到 1024 Token 才具备写入和命中条件，系统定期清理且无固定有效期。显式缓存需主动标记，5 分钟有效且命中重置。检查的后端请求未设置显式缓存标记。 [上下文缓存，2026-10-29 更新](https://help.aliyun.com/zh/model-studio/context-cache) | 实际轮次有无命中、隐式缓存落盘和逐条删除能力、人审及副本范围待证。 |
| 同上 | 回答和流式片段，用于当前轮回复 | API 定义 SSE 输出。G1/G2 与上行相同，G3/G4 可能存在独立响应日志副本。 [Chat Completions](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions) | 完整及中途取消输出的 TTL、按请求删除入口和权限、人审未知。 |
| `cosyvoice-v3-flash`，双向 WSS `/api-ws/v1/inference` | 合成请求文本，含规则或经处理的回答句段 | API 确认北京入口、模型标识与文本帧。G1/G2 提供通用约束。 [CosyVoice WebSocket](https://help.aliyun.com/zh/model-studio/cosyvoice-websocket-api) | 请求文字及缓存/备份期限、逐任务删除及权限、人审未知。 |
| 同上 | 实时合成音频，发送到设备播放 | API 确认返回二进制音频。G1/G2 提供通用约束。 [CosyVoice WebSocket](https://help.aliyun.com/zh/model-studio/cosyvoice-websocket-api) | 输出是否持久化、音频副本期限、逐任务删除及权限、人审未知。此链路使用预置音色。 |
| 三接口各自的服务日志、错误样本和支持副本 | 请求/任务标识、错误码与状态、用量及耗时。错误样本可能涉及正文，实际范围待证 | G3 证实平台通用的元数据审计及可选 SLS 投递，G5 证实脱敏工单入口线索。两个语音模型的字段及日志功能覆盖待查。 | 平台日志实际 TTL、删除入口及权限、风控/报错是否另存内容、样本用途及训练授权、人审条件和角色、工单与备份期限均未获三接口专属保障。SLS 路径只处理客户库副本。 |

本次未登录百炼控制台。工作空间标识、签约版本、实际模型快照、日志投递状态、RAM 授权、分处理方、诊断副本处理地点与删除回执均未取得账号证据。也未验证平台内逐条删除。模型监控公开查询窗口只界定可查询范围。

## 本地与转发链路

| 层 | 只读核验结果 | 待证范围 |
| --- | --- | --- |
| APK | 静态检查 `AnimalActivity.kt`、`AnimalUpload.kt`、`WakeReader.kt`、`CloudPcm.kt` 与 `VoiceTrace.kt`。采集、唤醒与播放使用内存缓冲及流式上传，所查正式链路未发现会话音频或正文写文件。日志点输出耗时、操作/段号与状态。Manifest 禁明文并关闭应用备份。设置功能有加密持久化配置。 | 未读取设备 logcat、缓存或已签装包。签名制品、Android 系统转储、故障/退出清理仍需用合成回归核验。 |
| 后端 | 已部署制品指针绑定 `b198a72`。`backend/animal/cloud.py`、`backend/dashscope.py` 和 `backend/voice.py` 与源码逐字节一致。WebSocket 入站配置空日志处理器，记录事件、轮次/分段编号、耗时、结果和计量。截至所查路径，协议及供应商异常归为固定失败原因。供应商 WSS 禁代理，HTTPS 客户端禁环境代理和重定向。未发现语音或文本的临时文件写入。 | 核对限于正式游戏入口及所列客户端。降级、断线、异常退出、TTL 的闭环未在本次重跑。部署目录抽查只涵盖指定文件类型。 |
| 正式单元与 journal | 核验时单元 disabled/inactive，19443 无监听。`StandardOutput=journal`、`StandardError=inherit`、`PrivateTmp=yes`、`ProtectSystem=strict`。持久 journal 目录存在，合并配置未见显式留存天数，业务元数据可能在轮转前落盘。正式发布目录 backend 下按 `pcm/wav/log/tmp` 后缀计数为 0，未见该单元专属临时目录。未读取日志内容、凭据或候选文件内容。 | journal 实际保存期限、轮转后副本及服务活动时临时目录状态未证。抽查不覆盖旧试验目录和系统备份。 |
| 主机内存落盘 | 主机有约 1.9 GiB file swap，正式单元 `MemorySwapMax=infinity`。`LimitCORE=infinity`，内核配置为管道式 core handler，Apport 单元处于 active。 | 禁换页、崩溃后禁止正文转储均缺配置证据。这里记录配置风险，未观察到音频或正文已落盘。 |
| SSH 转发与 HTTP 代理 | PR #26 `BuddySsh.kt` 内建 JSch 本地转发并强校验 SSH 主机密钥，内层 HTTPS/WSS 仍走项目 CA 校验。候选拓扑为 APK → SSH → 服务器回环 19443 的后端内建 TLS。核验时 ssh.service active，标准输出进 journal。80 有独立监听，既有 Caddy 不在该候选路由上。 | 正式设备 SSH 账号当时未启用。未检查共享代理的其他站点、系统 journal 正文或正式设备 SSH 运行日志。无实际端到端代理日志或外部采集器副本证据。 参照 TITA-68 正式部署和 TITA-70 复核记录。 [APK SSH 候选 PR](https://github.com/WeiXinChan/little-buddy/pull/26) |

## 专用服务隔离复验

2026-11-24 在正式主机以临时动态非 root 单元验证本 PR 的候选代码与资源限制。正式单元在核验窗口处于停用状态，继续使用上表所述旧制品，部署时须同时选择含进程保护的后端版本及更新的单元。

- 主机的 `core_pattern` 为 Apport 管道。Linux 可绕过进程的 `RLIMIT_CORE` 将转储交给管道处理器。专用单元配置 `MemorySwapMax=0` 和 `LimitCORE=0`，standalone 入口在加载 TLS 和供应商凭据前调用 `PR_SET_DUMPABLE=0`，失败时退出。 [Linux 内核 core 手册](https://kernel.googlesource.com/pub/scm/docs/man-pages/man-pages/%2B/refs/tags/man-pages-6.11/man/man5/core.5)
- 临时单元沿用 256 MiB 与 32 任务上限。两次启动在进程内确认有效 UID 非 0、`memory.swap.max=0`、core 软硬限制均为 0、`PR_GET_DUMPABLE=0`。首进程在私有临时目录写合成标记后触发 SIGABRT。服务管理器记录 `code=killed, status=6/ABRT`，自动重启一次，次进程确认标记不存在。该 PID 的 `COREDUMP_PID` 精确日志查询为 0 条。未采集转储正文。
- 另用 `--standalone --provider fake`、临时证书和合成凭据在 29443 回环验证。SIGABRT 前后严格 TLS 的 `/healthz` 均成功，重启换 PID，停止后监听释放。以独立发布目录运行 `select-release`，验证旧版→候选版→旧版的链接切换。两次验证后清理了临时单元和夹具。该回退测试覆盖发布链接切换，正式发布与回退需验同版单元以及后端保护。
- 独立复验时，可用仅含合成数据的瞬态单元，复制候选单元的 `DynamicUser`、`PrivateTmp`、`MemoryMax`、`TasksMax`、`MemorySwapMax`、`LimitCORE` 和 `Restart` 设置。进程调用 `disable_core_dumps()` 后，用 `prctl(3)`、`resource.getrlimit(resource.RLIMIT_CORE)` 与本进程 cgroup 的 `memory.swap.max` 检查有效值。记录其 PID 并触发 SIGABRT，检查退出类型、新 PID、私有临时标记和专属 PID 转储元数据。合成服务测试使用另选的空闲回环端口，切换脚本通过 `LITTLE_BUDDY_RELEASE_ROOT` 指定临时目录。

## 放行判断

本次证据支持复核现有接口选型和日志最小化实现。三接口账户侧的保留、删除、人审和诊断副本仍有空白，服务器尚未证实隔离交换及崩溃转储。按现有设计，童声云测继续暂停。后续可用合成输入验证正常结束、取消、失联、进程重启及 TTL，测试配置和正式配置分别留脱敏证据。对应账号保障、工程验证、用户明确批准及监护人授权齐备后再按既有流程放行。成人或合成结果仅覆盖相应路径的工程表现。
