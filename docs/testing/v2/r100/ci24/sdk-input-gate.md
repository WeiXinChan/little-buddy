CI24：固定source7、私有GHA空源的SDK输入门校准

接管方最新授权覆盖此前只静态方案。本轮只改host脚本/一次性诊断workflow/文档，不构建Android，不重跑source6，不修改生产source7、V1、模型/阈值、格式/音量、HAL属性或effects。九组设备门和source7完整原mic断言保留，管理/提示watermark/旧声音拒绝/零上传门不减少。

CI23原artifact14971848207 SHA f4441cc1695f17d6abaf5ed0df39f35b87447c7f3c9a9f09e828ff0a51982157已核。冷目录、旧READ拒绝、新nonce READ和7→6资源交接已有原件；两臂RPC218但guest均峰8/首秒后零，live均FAIL。不得改生产6，也不能由两低信号判source无关或SDK单因。HAL7.1、effect7.0、实际input handles54/70与所选0 effect chains仅描述对应快照。

## 私有隔离证明与API

只在GITHUB_ACTIONS=true/github-hosted、专用合成开关、emulator-5554及实际API36/ranchu/sdk_gphone64_x86_64和既有fingerprint下运行。SDK仍严格37.3.10/既有proto SHA。RUNNER_TEMP/v2-avd及v2-runtime须当前UID/700，服务器只能精确unix私有pulse.sock；Pulse PID为本run启动、同UID、实际pulseaudio，带-n和指定-F。用/proc/net/unix对应socket inode及Pulse fd证明该PID持有socket。

pactl只读sources/sinks/modules/clients/source-outputs：只能两个module-null-sink及对应v2_playback.monitor/m06_input.monitor，native协议仅unix；QEMU client PID须属于本run emulator进程树和UID，真实exe须emulator/qemu-system-x86_64，source-output若存在必须m06_input.monitor。另严格校验QEMU私有PA/server/source/sink环境项和音频参数。/proc命令和环境仅流式筛选精确音频白名单，不持久化/输出整份内容，非音频参数/凭据丢弃；未知音频server/driver或查询失败即拒绝启用。缺公开native消费计数仍UNAVAILABLE，私有绑定不是消费保真证明。

每个inject流仅首个实际getMicrophoneState值用于一次决策：已true只观察，不重置/再启用；false必须重新通过私有证明后setMicrophoneState(true)至多一次并实读。之后若false只记录，不循环重启。读/写均认证且各0.4秒RPC上限，观察线程在首包信号后120ms开始、约200ms采样，不在20ms producer调用API或隔离查询。journal只证明各采样点，不证明间隙全程状态或native消费。先stop/join该有界线程，再finally恢复false并实读；启动proof失败尚无线程时不join未启动线程，主异常保留并附清理失败。无隔离证据永不true，Mac/OPPO和环境源不在本实验授权内。

receipt使用initial_sdk_real_audio_enabled=false和private_null_only=true；真实流内变化/一次启用计数/恢复读回在独立nonce+fixture SHA journal，不能再以host_mic=False概括全程。validator核原fixture/nonce、格式、计数、派生payload hash与journal停止/恢复状态。

## 固定600ms全零前缀

仅用于本次SDK注册预热。源WAV与SHA、64960样本4.06秒、内部停顿逐字节不变；独立前缀9600个零样本、原300ms尾零，总79360样本/248个20ms包。派生payload SHA单列，前缀不计源正文。原150ms迟到/原RPC固定deadline不续期，native PCM仍8秒/128000上限；prefix和门是两项传输设施调整，成功也不能宣称单一根因。波形/source/capture同模型hits、RPC、live各自判读，失败和NOT_RUN保留。

## 只复用b2 Android制品

CI23 run45504346259 artifact14972612151属于b2ccf61d3ef002aa0b43cc488627d21038f4fdfc，未过期，ZIP digest6a4b056f8556c01abf09b649fb3487f17ccd20003c9dfb9c9931e93cd17b874e。GHA运行包main SHA7b9e5d7f988e40f33761f6664920c44b48a52901179ed841f0fbbe2bd791f47a、test SHA0b5db56484d287ca93ab5e39e34d885acb363b12f5dd5fc3123205b61fc59444。它们与本机签名产生的a2be/2266包分开记来源，不混哈希。

checkout depth2保留本次commit的b2父ref；若不能解析则fail，不忽略guard。git diff --no-renames对所有路径审查，只允许本轮scripts/m06、ci24文档和该workflow，任何app/资源/Gradle根设置/wrapper/verification等变更均拒绝复用。两个APK均验证hash后才复制，不fallback assemble。JVM标NOT_RUN，历史122=120PASS/2SKIP及global86 API26+36 SUCCESS归属b2。此是明确授权的一次诊断，不是可合入产品的永久制品缓存方案；PR36仍HOLD，常规Android构建门须在后续产品审定时恢复。

## STOP_ENQUEUE静态定位边界

实际7 session97在70562、6 session137在106426停止，晚于采样/注入但早于管理await截止；后者换回默认7/session153，不代表6一直录到断言末尾。原件无CAPTURE_EXCEPTION/窗口失焦直接原因在该点，不能按15秒时长定因。

源码候选：VoiceClient.pump每10ms调用InputGate.checkResponseDeadline/player.tick/gate.tick，异常统一fail(playback)→close/status/failed callback→Activity.newClient失败回调→stopVoice。InputGate对响应pending有wake/solo/lastSpeech+15000期限，fake Wire未提供完整真实后端应答，是与现有timeline一致的候选，但无直接reason日志不能认定。其他stopVoice调用包括Capture.failed、owner请求失代、onPause/FOCUS_LOSS、权限拒绝和onDestroy。若后续确需修产品，仅建议这些入口用固定enum reason+captureId/source/permitNonce/generation的最小日志，并配暂停owner/响应期限触发的确定性反例，不增timeout。本轮不改APK以加日志。

一次CI24待实际原件：安全门失败则不启用，源信号未到即不进入产品根因判断；Restore失败强失败。真实管理进入后才审原freshness矩阵。其余九组既有门照跑；不占手机、不新增音源/云调用、不修改SDK版本，不盲重跑旧CI。
