# 私有语音猜动物联调

调试包入口为「私有语音猜动物」。Python 规则负责题库、猜测、揭晓许可、完成数和再玩。服务沿用北京 Fun-ASR realtime 和 CosyVoice v3 flash（已有配置的音色），游戏路径的 LLM 请求量为零。ASR 只有最终文本，策略用完整词组、否定、多候选和当前许可判定。空转写或歧义进入澄清；明确短词在有效语境才生效。漏识别、误转写和真实 1.5 秒停顿体验由 OPPO 实测。

## 启动私有会话

服务器需要 Python 3.11+、`backend/requirements.txt` 中的固定依赖、systemd、既有 `sudo -n` 维护授权和私有语音服务的证书及百炼凭证文件。Mac 需要 SSH 和 Android Platform Tools，OPPO 需要已有受信任的开发 CA、USB 调试和麦克风许可。以下流程独立使用服务器和手机的 8444 端口。既有 8443 服务无需操作。

1. 在 Mac 开 SSH 转发。将 `服务器别名` 换成现有 SSH 目标。

   ```bash
   ssh -t -o ExitOnForwardFailure=yes -L 127.0.0.1:8444:127.0.0.1:8444 服务器别名
   ```

2. 在 SSH 终端进入本 PR 固定提交的检出目录，核对 Python 环境，生成一个本次独立游戏令牌并启动服务。令牌终端应处于无录制的受控环境。

   ```bash
   python3 --version
   python3 -c 'import httpx, websockets; print(httpx.__version__, websockets.__version__)'
   umask 077
   ANIMAL_TOKEN_FILE=$(mktemp /tmp/little-buddy-animal-token.XXXXXXXX)
   trap 'rm -f -- "$ANIMAL_TOKEN_FILE"' EXIT
   openssl rand -hex 32 > "$ANIMAL_TOKEN_FILE"
   cat "$ANIMAL_TOKEN_FILE"
   scripts/with-private-animal dashscope "$ANIMAL_TOKEN_FILE"
   rm -f -- "$ANIMAL_TOKEN_FILE"
   trap - EXIT
   ```

   若需要安装依赖，先在管理员维护的 Python 3.11+ 环境按 `python3 -m pip install -r backend/requirements.txt` 安装，确保启动脚本使用的 `/usr/bin/python3` 可导入依赖。启动后应出现 `animal_ready port=8444`。脚本在前台结束或 20 分钟到期时回收服务。脚本显示的 unit 名可用于 `sudo journalctl -u <unit>` 或 `sudo systemctl stop <unit>`。

3. 另开 Mac 终端，连接一台 OPPO。若多台设备在线，为每条 `adb` 命令加 `-s 手机序列号`。

   ```bash
   shasum -a 256 -c SHA256SUMS.txt
   adb devices
   adb install -r -g little-buddy-0.1.11-animal-private.apk
   adb install -r little-buddy-0.1.11-animal-private-test.apk
   adb reverse tcp:8444 tcp:8444
   adb reverse --list
   ```

4. 打开「私有语音猜动物」，填独立游戏令牌，地址保持 `wss://127.0.0.1:8444/v1/animal`，点开始。等「正在听」说话，做一局三题并说「再玩一次」，任选一次说话时停止再重开。真实可闻首段可由成人现场标记，音频日志只记录播放请求和播放头时钟。

如连不上，先核对 SSH 转发和 `adb reverse --list`，再检查已有 CA 和证书有效期、IP 或 localhost 是否在证书 SAN 中、游戏令牌是否填入正确入口。Mac 可用受信 CA 文件执行 `curl --cacert "$ANIMAL_CA_FILE" https://127.0.0.1:8444/healthz`，预期为 `ok`。服务终端记录固定原因和各阶段耗时。手机可用 `adb logcat -s AnimalTiming` 观察客户端播放。测试结束后停止 SSH 中的服务，Mac 执行 `adb reverse --remove tcp:8444`，关闭 SSH。回退时用本包首页的原「私有语音验证」入口与原 8443 转发配置。若必须恢复旧 APK，0.1.8 是同包名 `com.littlebuddy.sim` 的版本码 9，Android 通常会拒绝覆盖安装。先确认可清除应用本地数据和授权状态，再由设备持有人卸载当前包并安装原签名 APK。不要为回滚改动原 8443 服务。

## 协议与验收边界

控制对象用 `event` 和 `key`（会话与轮次）。上行 PCM 和封口沿用 v1 语音帧，只有本地检测到有效语音才激活 ASR。无声只发许可关联的控制事件。服务声明段及样本数，手机播放头越过该段尾部后发已播事件，服务确认后显示图片。整轮回执、段前缀、结束声明和音频释放齐备才允许续听。清局时丢弃内存转写、未提交状态和音频；日志只含时序、计数和固定原因。题库耗尽单列已完成数。

离线执行 `PYTHONPATH=.:backend python3 -m unittest discover -s backend/tests`。APK 与测试 APK 使用服务器已有工程签名。设备 instrumentation、成人 OPPO 真实语音、弱网和童声分别登记。童声继续受设计文档的数据放行条件约束。

## 私有 TLS 故障夹具

先按上方命令核验和安装两包。使用一台已授权、已信任现有开发 CA 的实验设备。服务端运行假供应商，真机使用 AudioRecord 和 AudioTrack，测试仅上传内存合成的固定 PCM，不上传麦克风采样，不调用百炼。每个场景独立启动一次，避免故障序列被上一次连接消费。

1. Mac 单独开启 SSH 转发，并在该 SSH 终端从固定提交的目录启动第一个场景。

   ```bash
   ssh -t -o ExitOnForwardFailure=yes -L 127.0.0.1:9444:127.0.0.1:9444 服务器别名
   # 在服务器 SSH 终端执行
   scripts/with-private-animal fixture asr
   ```

2. Mac 的另一个终端执行以下命令。`animalScenario` 必须与服务端一致。

   ```bash
   adb reverse tcp:9444 tcp:9444
   adb shell am instrument -w \
     -e class com.littlebuddy.AnimalPrivateActivityTest \
     -e animalScenario asr \
     com.littlebuddy.sim.test/com.littlebuddy.SimUiRunner
   ```

3. 每次先 Ctrl+C 停止上一个服务，将两端的 `asr` 换成下一场景，依次执行 `first-pcm`、`between`、`playing`、`release`、`late`、`blackhole`、`disconnect`。分别覆盖 等待 ASR 最终结果、TTS 首 PCM 挂起、揭晓后的段间挂起、播放头推进时停止、释放通知等待、旧段和整轮回执、TCP 黑洞及断流。夹具检查清图、归零、释放前不可重开、无旧会话自动采播以及手动新局。
4. 停服务并执行 `adb reverse --remove tcp:9444`。原模拟入口的自动测试另按 [模拟 APK 说明](animal-apk-validation.md) 启动 8765 服务并指定 `com.littlebuddy.AnimalActivityTest`。

本次服务器只执行后端 TLS 测试并构建 Android instrumentation。私有故障夹具的设备执行、锁屏、真人语音、实际弱网环境均分别登记。

## 实云合成探针

以下为修复前 PR #11 固定 `74dd7b2` 的探针证据，本次时序复验使用离线假供应商。原探针用 `scripts/probe-animal-cloud.py` 对同一进程里的回环 TLS 游戏路由发送合成语音。现有百炼凭证通过 systemd 注入，探针使用临时自签 localhost 证书。音频仅在内存生成、重采样和发送。探针用协议 ACK 模拟播放完成，设备播放由独立验收覆盖。

- 完整会话 1/1。三题提交数为 1、2、3，「再玩一次」后归零。无自动重试。另一次启动在本地 TLS 握手阶段失败，未打开游戏会话、未调用云。
- 服务端 4 次 ASR，上行 114560 样本（7.16 秒）。游戏 TTS 11 次、109 字符。合成输入另用 2 次 TTS、11 字符。LLM 0 次。此轮未读取账户账单，实际费用待账单。
- 4 次封口至最终 ASR 分别为 156、135、120、147 ms。封口至服务端发首 PCM 分别为 732、741、619、711 ms。该采样点早于 OPPO 收包和可闻首声。
