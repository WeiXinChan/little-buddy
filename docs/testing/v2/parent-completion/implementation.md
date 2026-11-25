本批交付本机系统认证→首次PIN/恢复→受保护设置/连接导入→执行侧限制，以及独立本地安全帮助。不是完整V2/远程归属/现网语音已交付的声明。

## 固定组合与隔离

产品树组合已合main `379045c50f0ea234f19401ba2b8c82fda75f0528`（PR43）与已独立通过的PR42 `9e1ca95b8958f0a1b97c1e18ef263d18ed624ce6`，作为显式依赖。PR42尚待root最终审合；本批不替代其历史CI证据。

缓存候审commit `a5f0e8736eb7de7d0136804cfb8bbea0114b3ea5` 在另一条本地分支，未push；本产品树没有该commit或cache helper/workflow改动。没有复制PR45未合后端代码。客户端已按冻结PR45/be33588的单failure协议实现，服务端组合待root合入/授权配置。

## 可达本机路径

日常仍是两眼。长按右下角进入家长验证；长按眼睛其他区域打开无云依赖的安全帮助，不授管理权限。首次设备满足Android11+且有安全锁屏时，worker创建独立AndroidKeystore EC认证密钥，UI只给“系统验证并初始化PIN”。密钥生成/设备已解锁/安装标识本身均不授予OwnerProof。

系统BiometricPrompt以强生物或DEVICE_CREDENTIAL调用auth-per-use签名操作，密钥timeout=0；结果必须是本次CryptoObject的Signature，之后仅在当前Activity仍前台并重新得到焦点时，为新页发起的OwnerChallenge签名。挑战含随机nonce、设备公钥指纹、具体初始化/恢复/导入操作与60秒期限；验证签名、绑定及一次消费后，ParentDomain仍在最终epoch/CAS/期限点核验才落盘。取消、HOME、旧callback、过期、错误签名/nonce/操作均不写入。PIN不保存在系统认证前等待框，不写日志。

这条信任链的含义是“当前本机系统认证持有人授权本应用操作”，不识别亲子关系、不证明远程家庭账号独占归属。系统凭据/生物登记的维护属于设备持有人信任边界，不能把手机解锁状态等同认证。远程配对issuer不存在，不伪装已配对；没有安装ID、默认PIN、测试proof、Intent extra或V1 token赋权。

本机密钥/记录已有而owner key缺失时不新建接管；AES key/记录损坏沿原密封store隔离。系统认证后设置/恢复6位PIN，成功后仍回验证页，不隐式生成Grant；忘记PIN使用新系统签名操作。记录保持音量/语速/时长/已有设备连接，恢复不清其他应用或远端配对。

PIN验证得到原真实Grant后可保存音量0–100、语速85–115%、单轮活动60–600秒及打开真实FeedbackPageFactory。本机记录schema2可保存这些设置和连接，仍可读内部旧schema1；不是读取V1产品数据。全部仍在noBackup/原AES-GCM封装内；旧默认字段仍编码72字节schema1，截断/尾随/未知值拒绝。

已发行V2 WSS地址与设备凭据的导入要求“先PIN页，再一次独立系统认证”的PROVISION_ENDPOINT挑战。只导入，不发行令牌、不将PIN当服务端权限。URI必须wss、无userinfo/query/fragment、准确/v2/voice、有效host/port；token只允许服务端既有32–256 alnum格式。地址/凭据加密保存，不进Intent、日志或显示已存明文；真实远端有效性只能在TLS连接时核验。

## 播放/帮助/生命周期实际接线

host只有读取并核对当前认证磁盘记录/密钥的worker快照后才启动已配置连接；记录丢失、被替换或隔离不凭旧内存凭据启动。原生AndroidTrack在写入前应用音量上限，play使用已保存语速/pitch1；每个新child连接的PlaybackBudget从首次awake listening开始单调计时，重复wake/listening不续期，到期实际关闭旧transport/recorder/player后回眼睛/新待唤醒。该上限不是预算/费用页面，也不是实际声学上限证明。

进入管理先结束当前儿童transport并确认本机录放释放，再给验证页；当前批次不声称M06“保留同一儿童会话并恢复旧音频”已实现。退出从新待唤醒开始。Activity暂停先撤销parent代际，随后取消系统prompt及本地帮助，异步释放音频；focus只使parent失效，真正Activity pause取消认证候选。重复focus/open不反复抢占刚完成的系统认证结果。Capture与VoiceClient在worker任务/输入/输出前还核当前前台代际，迟到旧回调不启动新帮助或收音。

R88-01客户端只从正常open/bound建立session/turn/epoch/revision；revoke不丢该scope。单failure的local_help只接受v1/safety_support_v1及review_unavailable|content_blocked，scope匹配才先interrupt旧音频/图片、转本地新代际。非法/旧/重复/未知help返回，不以failure自身学习scope，也不拿远端文本作fallback。未审候选不会交本地TTS。

帮助文字立即显示，独立于Keystore/网络及native关闭等待。只有旧录放确认释放、家长上限可从可信记录读取（全新域使用公开默认值）、且已安装系统engine有不需网络的中文voice时才播放固定本地文案。缺voice/资源隔离时文字仍可读，无云TTS/下载/新收费。帮助期间儿童recorder/上传已关闭；HOME、退出、换页取消提示代际。回眼睛是新待唤醒，不恢复旧儿童上下文。关闭次数、API离线voice标记和编译不是物理停声/无网络包/可懂度证据。

## 最小验证与原件

针对性JVM **17/17，失败0、跳过0，8.101s**，实际ParentDomain/OwnerReceipt/Codec/Model与JCA签名：签名一次、异钥、nonce篡改、等值期限、签名期间到期、不同设备、旧receipt不伤新receipt、首次写PIN必需签名、配置/恢复保留字段、最终写前撤销、错误操作/伪造challenge、内部schema1兼容/尾随拒绝、URI/参数边界、HOME前排队PIN缓冲清零、旧UI不复活、帮助不能自学scope/重复消费、时长等值/重复wake不续期、磁盘记录丢失/变化时child启动拒绝。JCA signer仅测试夹具，不是Android认证实测。

签名预检负控只改临时OwnerReceipt副本：同17项执行，16通过/1预期断言失败/0跳过，准确命中aDifferentSigningKeyCannotIssueOwnerProof，编译成功后JUnit退出1、runner识别退出0；不混正常分母。consume还保留独立签名复核，未将该负控冒称实际授权绕过。

首次编译遗漏新增FEEDBACK枚举分支已修，34s失败原件保留；额外AndroidTest请求遗漏已有v2Test开关，在任务查找阶段16s失败、未执行测试，原件另存。改用现有-Pv2Test后，应用＋AndroidTest源码编译/打包已成功（1m16s与中间1m7s不叠加为测试用例）。最终冻结源码的结果和APK hash见末尾。

所有构建离线、--no-daemon/--max-workers=1、同一heavy.lock独占。没有启动手机/Mac/模拟器/语音/声学测试，没有真实云调用或部署。按用户当前暂停设备/旧全量语音验收要求，新功能提交标注[skip ci]，不会主动发旧Android emulator workflow；Pending不是通过，root在最终集中测试窗口恢复正常CI。本次不改workflow，不改变PR42旧API26失败证据。该行为见[GitHub官方说明](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs)；root合主线时也须遵守当前暂停阶段，不把主线push自动测试当成本轮已获准验收。

实现所用API证据见[Android每次认证密钥](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder#setUserAuthenticationParameters(int,%20int))与[系统认证种类](https://developer.android.com/reference/android/hardware/biometrics/BiometricPrompt.Builder#setAllowedAuthenticators(int))；文档不证明OPPO已配置/验证或当前Android生命周期UI效果。

## 冻结构建与APK

最终 `--offline --no-daemon --max-workers=1 -Pv2Test :app:compileV2DebugKotlin :app:compileV2DebugAndroidTestKotlin :app:assembleV2Debug` 成功 **1m7s，51任务/6执行/45 up-to-date**。AndroidTest只编译、未执行。既有弃用/nullable诊断和本批proof冗余条件warning不计失败，也不作为已验证硬件路径。源码后续仅加说明与同逻辑可复用runner，无产品变更。

正常/负控实际使用外层with-existing-build-lock调用run-parent-completion-tests.py（相同源码、ROOT定位本worktree）。仓库复现命令为 `scripts/with-build-lock python3 scripts/v2-parent-completion-tests.py`，签名预检负控加 `--negative`；runner仅将ROOT规范为仓库位置，不新装依赖。

APK SHA-256 `d70b5d5db847776038bc9ea9076952616e1f96dde3a2007a861fd64e98ad7346`，包com.littlebuddy.sim.v2，versionCode13，基线版本名0.1.12-animal-private-v2-m04，min26/target36、arm64。使用既有Debug证书，SHA256 `7705f543347ae9ec1de4ae4b0dc24f73b0a472fb32ecc06cca0d112a8fe75e10`；apksigner退出0，aapt/metadata一致。用本批固定head/tree/hash识别内容，不依赖旧版本名推断功能；非正式发布。

后续最终授权体验的安装说明：`adb install -r little-buddy-v2-parent-completion.apk`，入口com.littlebuddy.sim.v2/com.littlebuddy.V2VoiceActivity；本轮未安装/请求用户解锁/系统认证或收音。签名冲突时不擅自卸载清数据。眼睛长按可用本地帮助；右下角长按进入本机系统认证→设置PIN→PIN验证→设置/反馈，需有合法V2地址和已发行凭据才导入连接并申请麦克风。当前未提供这些真实远端资源，不伪造现网可连。设备/控件/生命周期/声学集中最终一次验收，不扩成此批已通过。
