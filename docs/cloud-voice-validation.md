# 私有语音单轮验证

本阶段验证点击开始后的一句交流。原有本地模拟入口可离线运行。私有语音入口在播放完本轮所有分段后回到等待点击，停止、退到后台或重新开始会隔离旧轮次。

## 配置与顺序

1. 先通过本地回环测试验证 TLS、设备令牌、连续 PCM16 样本及断线清理。Python 3.11+ 环境安装 `backend/requirements.txt`，运行 `python3 -B -m unittest discover -s backend/tests -v`。测试用 OpenSSL 生成临时证书和合成样本，百炼适配测试使用本地替身。
2. 仅在获准的私有接口运行 `python3 -m backend.demo --host <私有监听地址> --cert <证书链> --key <私钥>`。默认绑定回环和使用假服务。后端从受限服务环境读取 `VOICE_DEVICE_TOKEN`，使用独立的随机令牌，例如由保管人通过秘密配置注入 48 个随机十六进制字符。手机端证书须受系统信任并匹配域名。受控网络仅开放测试设备所需的访问路径。可用 HTTPS `/healthz` 检查连通。
3. 验证 APK 校验和并安装。在「私有语音验证」填 `wss://<私有域名>:8443/v1/turn` 和设备令牌。点击开始，等待「正在听」后输入合成音或成人测试音，等待自动封口或点结束说话。假服务应播放两段提示音并回到点击入口。分别在连接、录音、等待和播放时点停止，确认没有旧片段播放，再开始一轮。无麦克风授权时先完成授权。
4. 按下文核对北京业务空间并注入 Key。取得云试跑放行并核实私有入口后，由后端管理员按下文配置服务并显式选择 `--provider dashscope`。
5. 首次真实调用输入合成的「你好，瓦力」，确认收到「你好」「我是瓦力」两段短回复。再按相同流程做成人 OPPO 验证。ASR 会接收本轮输入，只有匹配这句问候时才把预定义句子交给 LLM，输出经过短句白名单后进入 TTS。记录设备系统、试跑类别、封口至首段开播的耗时、是否完整播放及停止后是否有旧回复。证据使用计数、耗时和结果码，避免保留录音、完整文本和凭证。儿童云试验另行审批。

## 首期技术决策与北京配置

已选阿里云百炼华北 2（北京）。后端串联流式 ASR、文本 LLM 流和逐段流式 TTS，在 TTS 前检查句段。这样能分别观测识别、首段生成和合成，同时以分段边界控制播放及取消。保留现有 `Providers` 接口和离线替身。实时端到端语音、OpenAI 服务和通用多厂商框架均留在首期范围之外。下表中的 Chat Completions 兼容格式由百炼北京域名提供。

| 阶段 | 建议首测配置 | 官方文档确认的接口 |
| --- | --- | --- |
| ASR | `DASHSCOPE_ASR_MODEL=fun-asr-realtime` | 双工 WSS，`run-task`→`task-started`→16 kHz 单声道 PCM16→`finish-task`；取最终句 [Fun-ASR WebSocket](https://help.aliyun.com/en/model-studio/fun-asr-realtime-websocket-api) |
| 文本 LLM | `DASHSCOPE_LLM_MODEL=qwen-flash-2025-07-28` | HTTPS Chat Completions SSE，`stream=true` 且关闭思考；使用公开快照固定首测版本 [模型](https://help.aliyun.com/zh/model-studio/qwen-flash) · [请求格式](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions) |
| TTS | `DASHSCOPE_TTS_MODEL=cosyvoice-v3-flash`，`DASHSCOPE_TTS_VOICE=longanyang`（龙安洋，普通话） | 双工 WSS，`continue-task` 送文本，接收二进制 PCM 24 kHz [CosyVoice WebSocket](https://help.aliyun.com/zh/model-studio/cosyvoice-websocket-api/) · [音色](https://help.aliyun.com/zh/model-studio/cosyvoice-voice-list) · [采样率](https://help.aliyun.com/zh/model-studio/multimodal-timbre-list) |

设置 `DASHSCOPE_REGION=cn-beijing`，`DASHSCOPE_WORKSPACE` 填实际业务空间 ID。ASR 和 TTS 使用该空间域名的 `/api-ws/v1/inference`，LLM 使用同一域名的 `/compatible-mode/v1/chat/completions`。 [百炼 Base URL](https://help.aliyun.com/zh/model-studio/base-url)

账号持有人在百炼控制台切换到华北 2（北京）及目标业务空间，核对已持有的 Key 归属该空间且有效，逐项核对表中模型 ID 及系统音色，并确认试跑额度。工单只回报各项可用状态和不同的非秘密模型 ID。现阶段已核对公开接口和地域资料。账号内权限、模型和音色可用性以及完整接口兼容性仍待控制台与获准后的合成语音试跑确认。

## 后端 Key 注入和消费

主机源文件为 `/etc/little-buddy/voice/dashscope-api-key`，目录归 `root:root`，权限 `0700`，文件归 `root:root`，权限 `0600`。在服务器的可信交互 SSH 终端操作，关闭会话输入录制。凭证保管人可复制下列命令，再在隐藏输入提示出现后粘贴 Key 并回车。

```bash
sudo -v && (
  set +x
  set -o pipefail
  systemd-ask-password --echo=no --timeout=90s '北京百炼 API Key' |
    sudo -n bash -eu -c '
      umask 077
      dir=/etc/little-buddy/voice
      install -d -o root -g root -m 0700 "$dir"
      tmp=$(mktemp "$dir/.dashscope-api-key.XXXXXX")
      cleanup() { rm -f -- "$tmp"; }
      trap cleanup EXIT
      IFS= read -r key
      [[ "$key" =~ ^[[:alnum:]_-]+$ ]]
      printf "%s\n" "$key" > "$tmp"
      mv -fT -- "$tmp" "$dir/dashscope-api-key"
    '
) &&
sudo -n test -s /etc/little-buddy/voice/dashscope-api-key &&
  sudo -n stat -c '%a %U:%G %n' /etc/little-buddy/voice/dashscope-api-key
```

Key 从隐藏提示通过管道进入管理员进程，磁盘文件采用同目录原子替换。最后一条只检查存在、权限和属主。由管理员在获准的系统服务 `little-buddy-voice.service` 的 `[Service]` 加入：

```ini
LoadCredential=dashscope-api-key:/etc/little-buddy/voice/dashscope-api-key
```

服务使用专用非 root 账号运行。在显式启用 `--provider dashscope` 时，后端从 systemd 设定的 `$CREDENTIALS_DIRECTORY/dashscope-api-key` 读取，只用于发往百炼的鉴权。缺文件时启动失败。模型及业务空间变量单独设在服务配置，手机使用独立的设备令牌。注入 Key 本身不会启动服务或触发调用。轮换后，等获准运行时重启服务加载新 Key。 [systemd 凭证机制](https://www.freedesktop.org/software/systemd/man/252/systemd.exec.html)

## 协议

单个已认证 WSS 对应单轮，鉴权用 `Authorization: Bearer <设备令牌>`。服务端取得 ASR 就绪后送 `turn.ready`，手机随后打开麦克风。二进制头为版本 1、方向 1/2 和 32 位大端样本位置，负载为单声道小端 PCM16。上行为连续位置、16 kHz、最多 320,000 样本，`turn.end.samples` 为末尾后一位。下行为 24 kHz，位置每段归零，依次发送 `segment.start`、音频帧、`segment.end` 和 `reply.end`。安卓收到完整分段并核对样本数后进入顺序播放队列。任一时间仅允许一轮，断线后等待后端清理供应商连接再释放该轮名额。

供应商参考 [Fun-ASR WebSocket](https://help.aliyun.com/en/model-studio/fun-asr-realtime-websocket-api) · [百炼 Base URL](https://help.aliyun.com/zh/model-studio/base-url) · [CosyVoice WebSocket](https://help.aliyun.com/zh/model-studio/cosyvoice-websocket-api/)。

## 北京账号首轮真实探测

使用 `scripts/cloud-voice-smoke.py`，由临时 systemd 单元以动态非 root 账号执行。单元使用 `EnvironmentFile=/etc/little-buddy/voice/dashscope.env` 和上文的 `LoadCredential`，总运行上限 50 秒。探针默认先用 TTS 生成固定普通话问候，再在内存中用 FFmpeg 转为 16 kHz。单次完整探针最多请求 1 次 ASR、1 次 LLM 和 3 次 TTS。诊断参数 `--mode asr-ready` 和 `--mode llm-only` 各只尝试一次对应接口；`--shared-speech` 仅用于北京共享语音端点诊断。探针无需监听端口。

| 请求 | 端点 | 实测结果 | 耗时 |
| --- | --- | --- | ---: |
| TTS 合成输入 | 北京业务空间语音域名 | WebSocket 异常关闭，未取得音频 | 1341 ms |
| TTS 合成输入 | 北京共享语音域名，显式传业务空间头 | `AccessDenied`，未取得音频 | 1308 ms |
| Fun-ASR 就绪 | 北京共享语音域名，显式传业务空间头 | `AccessDenied`，未取得就绪信号，无音频上行 | 1277 ms |
| Qwen 文本 SSE | 北京业务空间域名 | HTTP 403，未取得回复 | 277 ms |

真实请求共四次，使用本页表格中的候选模型和音色。没有生成可供验证的 PCM，合成闭环、真实取消及成人 OPPO 待测。这些结果只能定位到上游访问被拒或异常断开，无法判断单个音色是否可用。由账号持有人核对北京业务空间成员权限、Key 对应的计费方案及对三项模型的授权范围。确认后再选择是否重试；当前没有证据支持改模型、音色或地域。 [百炼错误码](https://help.aliyun.com/en/model-studio/error-code)

## 北京候选模型复试

临时 systemd 单元逐项各调用一次。北京共享语音端点显式发送业务空间头，以取得结构化任务错误。LLM 使用北京业务空间域名。探针仅保留结构化错误码、匹配诊断白名单的消息片段和格式有效的请求 ID。

| 阶段 | 实际候选 | 结果 | 请求 ID | 耗时 |
| --- | --- | --- | --- | ---: |
| ASR 就绪 | `fun-asr-realtime` | WSS 任务错误 `AllocationQuota.FreeTierOnly`，消息已脱敏，无 PCM 上行 | 未提取到 | 1317 ms |
| 文本 LLM | `qwen-flash-2025-07-28` | HTTP 403，`insufficient_quota`，消息已脱敏 | `5d3b0708-07eb-991e-80ff-763a8730705e` | 285 ms |
| TTS 合成输入 | `cosyvoice-v3-flash` / `longanyang` | WSS 任务错误 `AllocationQuota.FreeTierOnly`，消息已脱敏，无 PCM 输出 | 未提取到 | 1299 ms |

百炼文档将 `AllocationQuota.FreeTierOnly` 归为免费额度耗尽且无法转为付费调用的场景。文本也返回额度错误。三个结果均未报模型不存在或音色不兼容，因此未尝试替代或发起完整轮次。Key 的具体模型授权范围仍需账号持有人在控制台核对。 [百炼错误码](https://help.aliyun.com/en/model-studio/error-code)
