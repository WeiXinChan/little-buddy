免费优先的2.1生图适配与操作交接

基线cf187d4d35490726e3ce996c6cbe3df678a65a67；实现前核查见design.md。仅后端供应商适配/独立取图/配置示例与证据；qwen4-max文本与审核、VoicePeer/协议/Android/RC8不变。真实模型请求0，未读取或修改实际secret/config、未部署/合并/新增服务。

配置

新增可审示例`backend/deploy/v2-image-free.example.json`：根审定workspace/resource_review_id后model=qwen-image-2.1-turbo、fallback_model=qwen-image-2.1-pro、free_tier_only=true，n=1/512固定。三个字段作为同一显式配置；免费策略声明缺失或非法、用3.0作后备、Pro回Turbo、翻译模型qwen-mt-image-2.0及非512均拒绝。`review_model=qwen4-max`和既有政策ID/专用key路径不变。默认未配置/disabled不调用；不能只把allowlist加个模型名。

可选管理员切换是model=Pro、fallback_model=""、free_tier_only=true。原3.0/b64仅兼容原显式primary配置，免费路由永远不回3.0或其他付费模型；本PR不改实际image.json，root须审查后切换配置才启用新路由。free_tier_only是管理员审定声明，不会替账户切开关，也不是额度/权限证明；root须确认两模型用完即停已生效。免费只指生图配额，qwen4-max审核/文本和语音仍可能计费，不保证整链免费。

路由

一次逻辑任务先审核最小prompt，再请求Turbo。仅HTTP403、≤16384原始字节严格JSON（拒绝重复键/非有限数）、精确AllocationQuota.FreeTierOnly、无data/output/usage等产图材料的已知错误结构才跳Pro一次。接受明确flat code/message/request_id或OpenAI error.code结构，不从message做子串猜测。未知403、AccountOverdue、429、超时、网络错误、混合/畸形响应、已成功返回URL后的下载/PNG/图审失败均终止当前尝试。两个模型共用原单任务/lease/总deadline，不重新计时，不生成多图。

观测到的耗尽模型在当前实例内跳过，两者均耗尽后新请求在prompt审核/网络前直接quota失败；无自动恢复/计时重试，root重新配置/重建实例才重置观察缓存。这不是成功张数计数，更不等于全账号10张余额。既有4逻辑尝试/滚动小时、间隔15秒仍保留；一次逻辑任务最多两个生图POST，只有首个明确未产图的免费额度错误允许第二个。失败继续沿既有image_status/安全固定语音交代，不改变聊天权限。

root转述截图为Turbo10/10、Pro10/10、2027-01-01到期且用完即停；本地未查询账户或验证权限。模型额度与其他账号/进程共享情况以控制台及真实服务返回为准；不造本地10张账本，不为明天到期的翻译额度制造调用。[官方免费额度规则](https://help.aliyun.com/zh/model-studio/new-free-quota)与[错误码说明](https://help.aliyun.com/en/model-studio/error-code)。真实计费/账户开关生效仍由root有限真实验证，不能据本地计数声称免费或3元/小时达标。

URL取图隔离

官方Qwen API示例提供精确host `dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com`，本批只有此白名单，不能配置成任意OSS或通配域名。[官方Qwen图像API](https://help.aliyun.com/zh/model-studio/qwen-image-generation-and-editing-api-reference)。实际若返回别的host/path格式，先失败关闭并由root核可信依据再改代码，不能临时放宽。

独立httpcore池使用现有锁定依赖，不借API的httpx客户端；无Bearer/default headers/cookies/netrc/环境proxy。只GET HTTPS/443，拒绝用户信息/片段/控制字/点路径/非PNG路径/超4096字符URL；绝不跟随redirect。DNS全部答案必须公网（拒绝混合私网、本地、保留/多播/过渡地址），验证后只连一个字面IP、无连接重试，TLS仍验证原host/SNI及默认可信证书。DNS/连接/TLS/每次流读写前后检查同一lease，避免一次True成为跨IO许可，也不在验证后重新按域名解析连接。

响应必须200、image/png、identity编码；严格length/实际字节≤2MiB、流式取回，pool/response必关闭。原JSON体/b64上限、checked_png真实尺寸/CRC/zlib/元数据去除、nonce/hash精确PNG图审和短期清除继续生效。成功URL永远不发给Android，只走原有审核后的PNG传输；URL、签名和缓冲不落盘/日志。清空自有bytearray，不承诺Python/网络库不可变副本物理覆写。

验证与root后续

新边界测试使用MockTransport、受控DNS/连接与真实PNG；覆盖free-only条件/错误体、单图已产后不可重试、双耗尽停止、DNS固定/TLS主机、URL/私网/header隔离、字节/MIME/PNG/图审、总deadline和取消。原图片适配/runtime/review/wire/description/静态素材套件也本地运行；不跑云、不读实际配置。证据中的URL签名/key均合成字符串，生产代码没有测试批准回执。

root审查后：从含本PR的最终main重打后端发行并核manifest，审核上述两字段差异和示例workspace等值，确认两个免费用完即停开关；在原预算内做有限真实单图链路验证，只记录model/状态/输出host/尺寸/hash等必要metadata，不记录signed URL/原内容/key。然后按既有授权切换后端配置与APK的匹配清单。root/v2-rc8和APK源码清单未改，无需仅因后端适配重建APK或改版本。host、实际PNG512支持、耗时和账号授权仍以该最终验证为准，本批不宣称云已测。
