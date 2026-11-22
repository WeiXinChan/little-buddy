# TITA-15 · Pipecat 私有语音实验

基线为 PR #6 的 `0707ffc6844c0c4c4ad9343c37a01fb694ae076a`。草稿 PR 以该提交所在的 `tita-12-private-voice` 分支为比较基准，评审时以本报告中的固定 SHA 为准。实验仅覆盖现有私有问候的两段回复。

## 管线与保留逻辑

每条经鉴权的 WSS 连接创建一个 Pipecat `PipelineTask`。管线用三个处理器调度采集识别、问候审核后调用 Qwen、审核分段并合成。连接断开由原服务检测，Pipecat 处理 `CancelFrame` 并取消该轮的处理任务。处理器传递获准的问候和有界的回复迭代器。后两级同步等待下游消费，保留原有单槽分段预读和 TTS 背压。

现有 WSS 握手、版本、ready、16 kHz PCM 上行、24 kHz PCM 下行、样本位置、分段号、错误码、提示词、内容审核和云适配器继续复用。ASR 和 TTS 清理仍由现有超时和任务所有权控制，前一段 TTS 清理可以与下一段合成重叠。连接收尾前最多仍可短暂返回 503 busy，不能让两轮同时占用云链路。安卓代码未进入实验变更。原 APK 继续使用既有短答、噪声与 1.5 秒端点规则。

PR #6 已知的 ASR 封口附近断开分类缺口仍由共用的 WSS 竞态及 ASR 处理路径继承。实验离线验证了封口等待时显式停止后的资源释放和新轮隔离。新增的失败面是 Pipecat 生命周期、框架异常转译、调度开销和依赖链。

## 离线复核

在仓库根目录串行运行。以下命令适用于服务器 Python 3.12，没有使用 Pipecat extras。若全局重任务锁被占用，等待持有方释放再开始。

```sh
python3 -m venv --without-pip ../pipecat-venv
flock -n -E 75 /var/lock/little-buddy/heavy.lock \
  python3 -m pip --python ../pipecat-venv/bin/python install \
  --only-binary=:all: -r experiments/pipecat/requirements.lock
python3 -m pip --python ../pipecat-venv/bin/python check
HF_HUB_OFFLINE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  ../pipecat-venv/bin/python -B -m unittest discover -s backend/tests
HF_HUB_OFFLINE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  ../pipecat-venv/bin/python -B -m unittest -v experiments.pipecat.test_pipeline
```

实验套件把既有假服务语音和 WSS 测试接到 Pipecat 入口，并在 ASR、LLM、TTS 注入取消后的迟到异常和 PCM。无需 APK、模拟器、录音文件或云密钥。

## 服务器对照

A/B 需要已有服务器凭证注入设施和合成成人音色的普通话问候文件（单声道、16 kHz、PCM s16le）。例如用 eSpeak NG 1.51 的 `cmn+m3` 以 130 词/分合成既有私有问候，再用 FFmpeg 转换。输入仅存放在工作目录，日志仅写版本、计时、资源与安全错误码。

```sh
experiments/pipecat/private.sh ab ../pipecat-venv ../synthetic.pcm
```

脚本检查 8444 和全局锁，通过现有 systemd `LoadCredential` 和 `EnvironmentFile` 注入配置。基线由固定 SHA 的归档启动，两个工作进程轮流监听 8444。顺序为 AB、BA、AB，各组首轮单列。两组的 HTTP 客户端分别保留至整组结束。两组使用同一音频和提示词，20 ms 一帧按实际时长送入，附 1.5 秒静音模拟端点时间。该静音单列。服务端封口后的差值从收到合法 `turn.end` 起算。合成文件本身可能已含少量尾音静默，测试没有运行安卓 VAD。

若本地合成样本在两组均无法通过问候门，可显式使用 `experiments/pipecat/private.sh ab-seed ../pipecat-venv`。该方式先用既有 CosyVoice 生成同一输入，额外计一次 TTS 请求。样本以匿名内存文件传入两组，并在进程退出时回收。

单次命令最多六轮，失败计入本次总预算。若首对同遭问候门拒绝，提前结束。命令也可在任一组启动失败时提前停止。按轮输出关联 ID、单调时钟事件、端点到首 PCM、分段间隔、CPU 时间及进程累计峰值 RSS。分段间隔定义为上一段 `segment.end` 发完到下一段第一帧 PCM 发出。暖轮样本只对成功轮汇总中位数和范围。服务端发包与手机播放时间各自计量。

## OPPO 待人工验收

1. 保持原 8443 会话和转发。在 Mac 另开一个终端，使用已有 SSH 目标并追加 `-L 127.0.0.1:8444:127.0.0.1:8444` 和 `-o ExitOnForwardFailure=yes`。在服务器仓库中用 `experiments/pipecat/private.sh fake ../pipecat-venv` 启动实验。假服务验协议后 Ctrl+C，再用同一命令将 `fake` 改为 `dashscope` 做云端体验。
2. 在 Mac 运行 `adb reverse tcp:8444 tcp:8444`，原 APK 私有语音入口使用 `wss://localhost:8444/v1/turn` 和既有设备令牌。继续信任原测试 CA 并保留证书主机名 `localhost`。如原手机轮次正在进行，等结束后再切换 App 内入口。
3. 按原有私有验收说明做两段回放、停止和重开。运行 `adb logcat -T 1 -v brief 'LittleBuddyVoice:D' '*:S' | tee little-buddy-8444-timing.log`，在独立文件采集 APK 的脱敏轮次日志，对照服务端 `turn_id`。用手机日志记录录音结束及播放事件，用人耳记录可闻首声和段间体验。测试成人与童声时分别标注。
4. 结束时把 App 入口恢复为 `wss://localhost:8443/v1/turn`。Ctrl+C 停实验命令及新 SSH 会话，再执行 `adb reverse --remove tcp:8444`。保留 8443 转发和原 CA。实验单元还有 15 分钟硬时限，退出只清理自己的进程和暂存目录。回退到固定基线只需继续用原入口。

## 对照报告

见 [服务器验证记录](results.md)。
