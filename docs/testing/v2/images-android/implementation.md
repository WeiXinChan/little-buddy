本批在 Android 生产路径接通 `images_v1`、默认图库与完整已播 ACK 后显图；保留 PR46 本机认证/PIN/播放设置及 PR45 单 failure 本地帮助。不是现网端点、设备声学或完整 V2 已验收声明。

## 依赖与文件边界

父提交为 PR46 `a9a883b9cf7ba4133452bc188043beea11b1f041`，tree `994d1a63cd35f159ed2eac0e49b7035311b2770e`。开工所见 main 为 `379045c`；本批显式叠加 PR46，不自行合并。冻结协议来自 PR47 `373f97cac98f8a4169e20fd007585123e61e6b43` 的 `docs/testing/v2/images-v1/protocol.md` 及实际 `backend/v2/voice.py`；只读，不复制未合后端。

差异仅 host、VoiceClient、图片路由/门控、V2 专属素材构建与对应测试/说明。parent 域、feedback 包、backend、V1 资源和候审 cache `a5f0e87` 均未改。本批 PR 以 PR46 分支为基线便于只看新增差异；root 合入依赖后可改目标 main。

## 生产路径

VoiceClient 在真实 bind 声明唯一 `features:["images_v1"]`；沿当前 WebSocket 实例/epoch，正常 open/bound 建立 session/turn/revision，不从 ready/reveal/failure 学习授权范围。图片 scope 还与当前 gate revision 相符。安全帮助原 scope/单 failure 分支不变，revoke 清图同时保留其帮助匹配所需 scope。

`image_ready` 只进入私有单槽，topic 允许是未来提交值。token 按服务端实际 `uuid4().hex` 的 32 位小写 hex 接收。仅 source=default、固定 fallback_reason 枚举、合法本地 ID/hash/512 尺寸；不接任意 URL/远端路径/正文。后台从打包 manifest 查唯一 ID，并重新核 SHA256 和解码尺寸；没有图片 IO 跨授权锁或音频线程。未知/损坏数据保持眼睛，不把客户端擅自替换的 garden 借原 token 显示。

显示必须命中同一准备 scope/topic/token/asset/hash，以及当前原生 player/stream 和 segment/end。只有 Playback 报 completed、未 suspended、当前 binding/revision，且实际 ACK 的 socket.send 接受后，才记录该完整坐标；部分、错误坐标、未发送的 ACK 不授显图。服务端 reveal 亦须命中该坐标，消费一次。图片可以先于或晚于 ACK 完成加载；没有 reveal 始终隐藏。

门控锁只覆盖内存决定和最终短 UI 发布。后台加载结果须匹配原 ticket；排入 UI 队列的通知不携带可直接显示的旧 Bitmap，UI 执行时再次读取门控状态。hide/revoke/新输入 advance/suspend/HOME/失焦/管理/帮助/退出先清 scope、slot、ACK 和代际，迟到读取/旧连接不能恢复新页。图显页仍可通过同一隐藏手势进入管理或本地帮助。没有 reveal 时日常只有两眼；真正会话关闭/活动时长到期清图回眼睛。`reply_end` 只是回答结束，不把刚揭晓的图片立即闪退；后续输入或显式 hide 清除。

默认库来源是已合的项目原创 60 图；Gradle 仅为 v2Debug 同步原 manifest 和 PNG，不打包 SVG/生成器。构建先核 ID 唯一、SHA256、PNG 头和 512 尺寸；产物脚本再核 APK 中 manifest 逐字节一致及 60 PNG、精确目录白名单。支持 garden 及 cloud-dragon 等连字符 ID。服务端 generate 缺动态 Provider 时仍 source=default/dynamic_unavailable；客户端不显示“生成成功”。私事/未揭谜底的语义限制由 PR47 审核/规划门控负责，Android 不从素材或准备事件推测/提前展示答案。

## 管理退出及仍缺资源

管理入口先撤销图片并关闭旧儿童录放，退出/取消撤销 Grant、释放页面，重新读取已认证配置后回到两眼及新连接待唤醒；不会借新页权限/旧图片/旧音频恢复。重复 focus 不替换活跃的眼睛图片路由。该安全重入不等于同一服务端儿童会话恢复：当前后端仅有 stop/suspend/resume_noise，没有管理挂起/恢复契约；已关闭 session 不可恢复。有限本地语音退出及保留同一儿童会话仍 OPEN，不能用恢复未审音频替代。

PR46 的首次系统认证/PIN 恢复与播放设置原样保留。本机系统凭据持有人不等于远端家庭归属；API26–29、远端 issuer/恢复服务、可信时间/设备绑定、真实 V2 WSS 与独立已发行 token、反馈 Provider/外部全副本删除、动态图像 Provider 继续集中列为 OPEN，详见 `../parent-completion/resources.md`。没有复用 V1 token、部署新服务或生成虚构 proof。

## 验证边界

正常 ImageGate JVM 12/12，失败0、跳过0：隐藏未来 topic、完整 ACK、加载/ACK 任意顺序、四坐标、各 scope/topic/token/hash、清理迟到、新连接同 wire scope、替换旧 token、解码失败和排队 UI 复核。移除 ACK 坐标门槛的临时副本编译成功，同12项中9通过/3预期失败/0跳过，原断言保留；不混正常分母。未执行设备 UI 或真实 AudioTrack，纯 JVM 用字符串代表 Bitmap，生产 Android 路由只做编译/源码核对。

实际命令：全局既有 heavy.lock 包裹 `python3 scripts/v2-image-gate-tests.py` 和 `--negative`；Android 离线 `--no-daemon --max-workers=1 -Pv2Test :app:compileV2DebugKotlin :app:compileV2DebugAndroidTestKotlin :app:assembleV2Debug`。没有重跑旧完整集合。Gradle DSL 名称遮蔽、路由类型推断循环两次编译失败原件分别保留；显式修正原因后复编，不计测试通过。协议 token 修正期间的一次成功中间 APK 未交付，字节码复核发现旧格式后另冻结构建，最终 APK 单独记录 SHA。

按用户暂停设备/语音验收要求，提交使用 `[skip ci]`，不启动手机/Mac/模拟器/HDA/旧 CI 或云样音。没有真机认证、图像实际屏幕、儿童体验、声学或长稳结果；Pending 不算通过。最终 APK、版本/签名和冻结编译结果由附件 identity.json/日志标识；安装仅为后续授权最终测试说明：`adb install -r little-buddy-v2-images.apk`，签名冲突时不擅自卸载或清数据。
