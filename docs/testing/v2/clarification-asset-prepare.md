# 固定澄清素材：仅prepare交审

文本固定为“我没听清，可以再说一遍吗？”，13个Unicode字符（含标点），不是实际账单字符结论。只读现生产配置确认 `cosyvoice-v3-flash` / `longanyang`，未读取或生成用户录音。

脚本 `scripts/v2_clarification_asset.py` 默认disabled；只能prepare或显式execute，不能传任意文本/模型/音色/采样率。生产依赖pin main19215a5的Git对象，工具单独pin冻结工具提交，避免自引用哈希。当前没有真实PCM，其SHA未知，禁止静音/假波形填充。

API复用 `backend/dashscope.py:276–296` 与 V2Speech：同一既有workspace WSS/TLS，run-task(audio/tts/SpeechSynthesizer)→task-started→一次continue-task固定文本→finish-task→binary PCM→task-finished。不改endpoint或SDK。format=pcm、sample_rate=24000、PlainText、enable_ssml=false。原生AndroidTrack.kt:23–31为24kHz/mono/PCM16，因此无需重采样，原始输出按PCM16LE单声道交付。

官方契约：[客户端事件](https://help.aliyun.com/en/model-studio/cosyvoice-client-events)、[服务端事件](https://help.aliyun.com/en/model-studio/cosyvoice-server-events)。usage.characters是任务累计值，取task-finished有效终值，缺失取此前有效最大累计值，不相加；未知null。必须先经过原SpeechTask.task_id校验，再读取usage；错误任务/失败不得生成可用素材。只保留数值usage，不保存provider body、转写、URL、token或异常message。

硬上限：TTS尝试1（socket I/O前预扣并落固定计数）、ASR/LLM/image均0，无fallback/retry。数据最多288000bytes，即6秒24k/16bit/mono；这只是机械容量上限，不宣称语音语义/声学已合格。操作timeout15秒，取消后的原V2资源确认退出仍受0.5秒边界；外层20秒watchdog，必要TERM/KILL各最多1秒回收，forced exit绝不当cleanup已确认。父/子继承同一heavy.lock FD9并核cgroup/2GB边界，不新建常驻服务。无自动重跑；输出目录已存在即拒绝。

输出目录0700、文件0600：成功有clarification.pcm、result.json及supervisor.json；失败可保留partial.pcm，不能入APK。记录原PCM SHA256、bytes/samples/duration、文本SHA、采样格式、模型/音色、生产和工具source、工具SHA、实际尝试、累计usage、退出与清理证明。supervisor同时记录result.json的SHA，可独立核对元数据。只在task-finished+真实资源退出确认+完整非空偶数字节PCM通过时标asset_generated_not_auditioned，仍apk_approved=false。固定素材不含家庭内容，但不自动公开；root试听/字词及长度核对后才交Android打包，后续本地播放无需每次云调用。

成本：本次prepare真实调用0；未来唯一请求的实际characters需取响应。实时额度、账单、价格均未知，不宣称免费或已扣费；尊重已有免费优先/用完即停，额度/auth/model失败直接停，不换服务。没有新增“必须实时证明免费才能执行”门槛。

离线验证只用明确synthetic mock：固定载荷/正确顺序/累计usage非相加、错误task_id、缺失终态、quota失败、默认disabled、固定参数拒绝、第二次I/O拒绝、模型不符、私有权限、完整原始字节/SHA及清理负控。另复用现V2Speech本地释放测试。最初缺sparse原QA文件导致加载错误，补齐原仓库文件后通过，原日志保留，不改skip。

冻结后root可审命令（准备不调用云；执行须root另放行）：

```sh
sudo -n python3 -I -B scripts/v2_clarification_asset.py --prepare --tool-source TOOL_SHA --output /home/ubuntu/tech/v2-delivery/clarification-asset-prepare-TOOL_SHA
# 以下本轮禁止运行；root审后明确放行一次才使用另一全新目录：
sudo -n scripts/with-build-lock python3 -I -B scripts/v2_clarification_asset.py --execute --tool-source TOOL_SHA --output /home/ubuntu/tech/v2-delivery/clarification-asset-once-TOOL_SHA
```

不能复用prepare目录作为execute目录，不自动将素材提交Git/复制APK，不改后端wire/服务或Android工作树。
