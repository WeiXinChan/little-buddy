# 私有语音单轮验证

本阶段验证点击开始后的一句交流。原有本地模拟入口可离线运行。私有语音入口在播放完本轮所有分段后回到等待点击，停止、退到后台或重新开始会隔离旧轮次。

## 配置与顺序

1. 先通过本地回环测试验证 TLS、设备令牌、连续 PCM16 样本及断线清理。Python 3.11+ 环境安装 `backend/requirements.txt`，运行 `python3 -B -m unittest discover -s backend/tests -v`。测试用 OpenSSL 生成临时证书和合成样本，百炼适配测试使用本地替身。
2. 仅在获准的私有接口运行 `python3 -m backend.demo --host <私有监听地址> --cert <证书链> --key <私钥>`。默认绑定回环和使用假服务。后端从受限服务环境读取 `VOICE_DEVICE_TOKEN`，使用独立的随机令牌，例如由保管人通过秘密配置注入 48 个随机十六进制字符。手机端证书须受系统信任并匹配域名。受控网络仅开放测试设备所需的访问路径。可用 HTTPS `/healthz` 检查连通。
3. 验证 APK 校验和并安装。在「私有语音验证」填 `wss://<私有域名>:8443/v1/turn` 和设备令牌。点击开始，等待「正在听」后输入合成音或成人测试音，等待自动封口或点结束说话。假服务应播放两段提示音并回到点击入口。分别在连接、录音、等待和播放时点停止，确认没有旧片段播放，再开始一轮。无麦克风授权时先完成授权。
4. 云端联调前，凭证保管人核实业务空间地域、模型/音色权限和试跑额度。把 `DASHSCOPE_API_KEY`、`DASHSCOPE_WORKSPACE`、`DASHSCOPE_REGION`、`DASHSCOPE_ASR_MODEL`、`DASHSCOPE_LLM_MODEL`、`DASHSCOPE_TTS_MODEL` 和 `DASHSCOPE_TTS_VOICE` 注入后端服务账户的受限环境。当前适配支持北京 `cn-beijing` 和新加坡 `ap-southeast-1` 的业务空间域名。按空间确认 Fun-ASR-Realtime、Qwen Flash 和 CosyVoice Flash 的具体模型及系统音色后，在同一启动命令追加 `--provider dashscope`。云 Key 和设备令牌各自保管，工单只记录配置状态和地域。
5. 首次真实调用输入合成的「你好，瓦力」，确认收到「你好」「我是瓦力」两段短回复。再按相同流程做成人 OPPO 验证。ASR 会接收本轮输入，只有匹配这句问候时才把预定义句子交给 LLM，输出经过短句白名单后进入 TTS。记录设备系统、试跑类别、封口至首段开播的耗时、是否完整播放及停止后是否有旧回复。证据使用计数、耗时和结果码，避免保留录音、完整文本和凭证。儿童云试验另行审批。

## 协议

单个已认证 WSS 对应单轮，鉴权用 `Authorization: Bearer <设备令牌>`。服务端取得 ASR 就绪后送 `turn.ready`，手机随后打开麦克风。二进制头为版本 1、方向 1/2 和 32 位大端样本位置，负载为单声道小端 PCM16。上行为连续位置、16 kHz、最多 320,000 样本，`turn.end.samples` 为末尾后一位。下行为 24 kHz，位置每段归零，依次发送 `segment.start`、音频帧、`segment.end` 和 `reply.end`。安卓收到完整分段并核对样本数后进入顺序播放队列。任一时间仅允许一轮，断线后等待后端清理供应商连接再释放该轮名额。

供应商参考 [Fun-ASR WebSocket](https://help.aliyun.com/en/model-studio/fun-asr-realtime-websocket-api) · [百炼 Base URL](https://help.aliyun.com/zh/model-studio/base-url) · [CosyVoice WebSocket](https://help.aliyun.com/zh/model-studio/cosyvoice-websocket-api/)。
