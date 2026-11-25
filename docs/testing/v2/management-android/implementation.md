本批接通 Android 当前认证 WS 的管理挂起/同会话退出待唤醒、专用本地取消检测和旧安卓系统指纹签名路径。没有部署后端、发行 token、设备或声学验收。

## 固定依赖及协议

父提交为 PR50 `4874f5643c4384944602db336922f9da0cde70e5` / tree `6685f7de999dc7c9807a01a4ca59db390c59d284`，继续包含 PR46 的认证、PIN、配置及帮助。后端只读冻结 PR51 `36375242b28fb945c5ef26ce4b7f38932c197ba4` 的 `docs/testing/v2/management-v1.md` 与 `backend/v2/voice.py`；它另依赖 PR49。此树不复制后端、feedback、cache 候审差异，不改 V1 唤醒实现/词表。

ManagementState 只从当前普通 open/bound 或主动请求的正常 scope 获取 session/turn/revision。管理状态、失败帧不能建立 scope。新参与者必须先有当前普通 scope；旧暂停 receipt 不能借新参与者或旧页操作恢复。pause/resume 各增加一次 epoch/revision，seq 从0重新开始；scope/paused/waiting确认须匹配预留值。receipt 只保存内存，一次消费，不能充当 PIN/Grant，不能修改配置。待确认阶段有4秒控制超时；失败、未知释放进入保守 quarantine。后端最终协议没有 expires 字段，客户端不虚构 wire 期限；保留原播放 budget，不因管理/heartbeat/waiting或重复wake续期，修改时长仅可收紧当前预算。服务端仍负责原 idle TTL/lease 与上下文过期。

## host/媒体/页面的实际顺序

主线程先使儿童 capture 的 allowed 为假并清图，音频 owner 先停旧 player 并确认释放，再停止儿童 recorder并等待有限释放，之后才发scope→management_pause。没有先把儿童麦克风交给管理识别再撤销儿童上传。暂停确认前也屏蔽旧audio/open/bound/决定/图片等回调，只允许控制/失败/撤销；失败不学习任何恢复 scope。

收到当前paused确认才展示家长页；没有可用连接仍可打开本机验证页，但不合成receipt或声称保留服务端上下文。管理页退出/取消不需 PIN，必须是当前页操作：关闭原页/清Grant、停止专用本地 recorder、重读当前密封配置后，用同一WS当前receipt请求resume；等待服务端waiting_wake确认后，才新建儿童本地唤醒capture。waiting期间及未真实唤醒前没有儿童PCM上传，不重建旧player、不恢复旧音频。settings的音量/语速用于之后新建的AndroidTrack；原时长预算不延长。退出时换成新眼睛路由，VoiceClient也换到对应图片槽，不能把后续reveal落到旧脱离窗口的View。

正常当前页退出会清Grant，但不等同后台/安全撤销。失焦/HOME/销毁、Grant到期/异常锁定、PIN改变、系统认证重入等关闭旧连接并撤销transport代际；迟到resume/旧按钮/旧KWS结果不能恢复旧页或把receipt借给新连接。普通取消不自动恢复管理权限。控制或原生资源释放无法确认则保持quarantine，不开第二个recorder；资源正常结束/过期也不能复用旧receipt。主UI代际与transport代际分离，正常管理切页不会误杀本来应保留的认证WS。

专用ManagementCapture复用已存在、已打包的sherpa KWS模型/调度模式，只装 `取消`、`退出管理页面` 两条词表。它没有VoiceClient/网络PCM端口/ASR正文/录音文件，不识别任意谈话；只交一个当前页退出回调。仅在有现成录音权限、前台/焦点/管理代际有效且旧设备已释放时启用，不在家长页弹权限请求。失焦先撤销、退出有限join，未知原生构造/释放失败隔离。最多本地监听600秒，无命中也不上传。关键词tokens逐项在现有模型词表中校验，只证明词条可装配，不证明童声准确率或没有误触发。儿童与管理recorder的原生证据分开观察，不用后者替换旧儿童释放证据。

PR51新增正常 `session_end`：仅当前连接/epoch和既有普通scope、reason=conversation_ended可消费，先清图/关旧transport及硬件，再回新待唤醒路径；不把revoke或网络失败当正常告别，不从结束帧学习scope。之后只能新认证连接/新Session，不复活已关闭会话。

## API26–29认证最小设计与实现

先保留已有信任边界：设备持有人授权不等于远端家庭归属。Android11+继续强生物/系统凭据CryptoObject；Android8–10仅支持系统已登记的硬件指纹，Keystore EC私钥要求每次使用认证（validity=-1、登记改变失效）。不启用设备解锁有效期窗口，也不把isDeviceSecure/硬件存在/点击确认当proof。

先初始化本次Signature，再把完全相同的对象交FingerprintManager.CryptoObject。取消/错误/HOME/旧serial结果不交付；成功还须result内签名对象身份一致。回前台新页后仍走原随机nonce/设备公钥/操作/期限绑定、一次OwnerReceipt及域最终提交，不保存系统认证前PIN、不自动授Grant。旧owner key缺失/失效不重建接管，远端issuer仍缺。自绘提示框只显示操作说明和取消，不具备签名权限；安全决定来自系统指纹/Keystore签名。无硬件指纹/未登记者仍默认拒绝，设备凭据fallback在这些系统继续OPEN。

依据[Android KeyGenParameterSpec官方说明](https://developer.android.com/reference/android/security/keystore/KeyGenParameterSpec.Builder#setUserAuthenticationValidityDurationSeconds(int))：per-use与认证有效时间窗不同；该文档不证明本机实际指纹/设备操作已成功。本批只编译此平台代码、复核JCA签名边界，不冒称API26/OPPO真机认证通过。

## 验证和发布边界

本批新增ManagementState/实际ParentPanelModel撤销定向测试16项；正常与scope负控日志分列，负控只改临时副本，不弱化原断言。首次15项中2失败是夹具把既有Grant闲置期限写成60秒，原件保留；改用生产IDLE_MS=120秒后原撤销断言通过，再新增正常换人scope边界成为16项。原认证/配置/帮助17项与图片门控12项按影响抽查，未运行旧全部集合。JVM不能执行Android系统认证/KWS/真实AudioRecord或屏幕，字符串/注入存储仅测试夹具。

命令均由既有 `/var/lock/little-buddy/heavy.lock` 串行包裹：`python3 scripts/v2-management-tests.py`、`--negative`、`v2-parent-completion-tests.py`、`v2-image-gate-tests.py`；离线Gradle `--no-daemon --max-workers=1 -Pv2Test :app:compileV2DebugKotlin :app:compileV2DebugAndroidTestKotlin :app:assembleV2Debug`。AndroidTest只编译，不设备执行；APK核60图SHA、manifest及管理词表/权限，版本/签名/最终SHA见附件identity.json。中间构建日志保留，不累加为测试分母。

完整跨功能、设备/童声/声学/长稳最终集中。无Mac/手机/模拟器/HDA、云样音、部署、付费或旧CI重跑。提交[skip ci]，Pending不是通过。剩余资源继续列在 `../parent-completion/resources.md`；M14受控签名/版本/回退准备见同目录 `release-checklist.md`，不要求用户过程操作。
