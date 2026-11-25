## 本批集中精确资源缺口（按功能分开）

只读已授权项目资源的元数据：既有service-env/provider key/V1 token/回环证书及私钥存在、root持有0600、普通非symlink文件；已有证书当前在有效期且含127.0.0.1 IP SAN。没有读取或回传token/key正文，证书域名未输出；未证明公众信任链。当前`/etc/little-buddy-v2`和`/opt/little-buddy-v2`均不存在；本用户pip wheel缓存列表为空，发行是完整来源包而非自带wheel/已安装环境。root需从已授权依赖源备齐锁定wheel，本次不联网下载或改系统依赖。无V2部署/发行token或新云调用。

| 功能/现有接口 | 缺的精确值或权限 | 影响/当前可用路径 | root凭现资源能否完成 |
| --- | --- | --- | --- |
| V2入口：live回环19483 `/v2/voice`；device-scope.json.endpoint | 获准外部wss authority/路由；独立`v2-device-token`和同token SHA256、not_after、protocol_contract；安全领取/撤销负责人 | 后端可离线校验、真实本地TLS运行；尚无远端家庭实际可连证明。V1 token不代表V2授权 | 已有主机/代理资源可供root审后划独立路径，但本次未批准部署，不代root改配置；token是设备运行凭据，不签家庭OwnerProof |
| 两腿TLS：`--cert/--key/--ca-file/--tls-name`与APK外部endpoint | 受审回环trust-anchor完整链；外部endpoint证书SAN/链、代理上游验证/SNI、APK信任配置 | 已有回环证书SAN/日期可用；离线验链只证明所给CA信任，不能证明公网CA或APK已信任 | root可核已有证书/代理映射；外部域名控制/CA信任若不在现授权内需对应维护者，不由本机root替代远端信任 |
| 聊天/四玩法/语音：`runtime.settings`六字段、DashScope构造 | V2实例对既有workspace/key的受控读取权限、锁定wheelhouse；当日额度与数据条件沿现授权最终核验 | 已接真实适配；不需要另造LLM平台。现模型值已核，依赖实际版本锁定；供应商可用性非本批测量 | root在现有授权内可提供LoadCredential材料/离线wheel，不能将可读key推断为所有模型/场景已获许可 |
| 反馈远端：Android `FeedbackProvider.available/submit(idempotencyKey,payload,admit)/withdraw`、DeleteReceipt.allCopiesDeleted | 受审工单端点/凭据/device绑定、维护者、超时按原幂等key撤回、正文/日志/缓存/备份全副本删除回执与期限责任 | 本地vault/outbox/sweep可用，真实远端默认Unavailable；本发行不是反馈平台，不假提交/删除 | root需选择并取得平台维护者/删除条件；不能把现GitHub/Multica访问权推断为儿童工单及全副本删除权限 |
| 动态图片：`UnifiedProviders.prepare_visual`→`DefaultImages.prepare/accepts` | 合规图像Provider端点/模型授权、输入输出保留与删除/内容审核条件、可取消适配和受审资源映射 | 60默认PNG已真实准备/门控/回退；generate当前明确default/dynamic_unavailable。并无可填一个URL就启用的远端字节生产适配 | 既有DashScope key不证明图像权限；root可核现供应商条件后安排独立适配，不能本批擅自开通/收费或伪称生成 |
| API26–29归属初始化/恢复/端点配置：`OwnerProof.consume(OwnerChallenge)`，operation INITIALIZE_PIN/RESET_PIN/PROVISION_ENDPOINT | 已注册issuer/验证密钥、fresh单次device-bound nonce/operation/expiry签发与撤销渠道、实际设备绑定记录；b30核API分支实际系统认证能力 | 本发行不发OwnerProof；当前依赖树UnconfiguredOwnerProof拒绝。b30新组合本地系统认证另验，不能把系统解锁当家庭/远端配对归属 | 服务器root凭据不能证明手机家庭归属；需要真正issuer与绑定机制，若已有项目服务则提供其受审接口/维护者，不能伪造proof |
| 保留期限/设备凭据代际绑定：`FeedbackClock.now():Long?`与vault高水位/设备状态 | 有认证且绑定设备/凭据代际的可信时间/撤销源、断网/重置恢复信任规则 | 系统时间与连续性高水位不是跨设备可信时间；本次服务器token not_after也不替代Android可信时钟，不能因此宣称D02/D06完成 | root可提供受审服务时间接口，但需确证设备绑定及恢复策略；无该服务继续OPEN，不放宽TTL |

需要root统一收口的最小资源询问（仅当现有项目授权确实无法定位）：请一次确认已有V2端点/凭据发行负责人、反馈平台维护者、动态图像服务供应商及设备归属issuer的资源指针；各项可答“暂无”。不在评论索取密钥、个人资料或要求用户做过程测试。能从既有资源完成的由root自行审定执行；暂无项分别OPEN，不混成“全部不可用”或以本地默认路径冒充远端能力。
