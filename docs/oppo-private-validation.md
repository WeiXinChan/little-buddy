# 成人 OPPO 私有联调

## 首次连接

依赖现有 Mac SSH 访问、Android Platform Tools、支持 USB 调试的 OPPO、服务端能执行 `sudo -n` 的授权维护账号。服务端已准备 30 天 localhost 开发证书与独立设备令牌。应用调试变体只对 localhost/127.0.0.1 增加系统用户 CA 信任，仍校验证书链和主机名。

1. 在 Mac 下载工单的两个 APK、CA 和 `SHA256SUMS`。运行 `shasum -a 256 -c SHA256SUMS`。核对 CA 后将 `little-buddy-loopback-ca.cer` 安装到 OPPO 的用户 CA 存储。安装菜单随 ColorOS 版本变化。只在本次测试设备安装，验收后移除。
2. 登录原服务器，切到本 PR 分支的仓库目录。约定两个终端。第一个从 Mac 启动有转发的 SSH 会话，服务器提示符内运行 `scripts/with-private-voice fake`。确认假服务后用 Ctrl+C 停止，再按同样方式运行 `scripts/with-private-voice dashscope`。每次服务只监听服务器 `127.0.0.1:8443`，20 分钟自动结束。

   ```bash
   ssh -t -o ExitOnForwardFailure=yes -L 127.0.0.1:8443:127.0.0.1:8443 <已有SSH目标>
   ```

   设备令牌由服务器管理员在无录制的受控 SSH 终端查看 `sudo -n cat /etc/little-buddy/voice/device-token`，仅填到手机密码栏。后台以 `LoadCredential` 加载。百炼 Key 由另一路凭证加载。
3. OPPO USB 连接 Mac，解锁并允许 USB 调试。在第二个 Mac 终端运行：

   ```bash
   adb devices
   adb install -r little-buddy-0.1.4-voice-lab-debug.apk
   adb reverse tcp:8443 tcp:8443
   adb install -r little-buddy-0.1.4-voice-lab-instrumentation.apk
   adb shell am instrument -w com.littlebuddy.sim.test/com.littlebuddy.SimUiRunner
   adb logcat -s LittleBuddyVoice:D
   ```

   多设备时给每条 adb 命令加 `-s <序列号>`。在「私有语音验证」输入 `wss://localhost:8443/v1/turn` 和设备令牌。点击开始，等待「正在听」，由成年测试者说已约定的短问候。先验假服务两段提示音，再验真实云回复。
4. 验收后 Ctrl+C 关闭服务器命令及 SSH 会话，运行 `adb reverse --remove tcp:8443` 并从 OPPO 移除测试 CA。这条隧道仅用于开发验收。

## 观测与验收

- 第二个终端的 Android 日志记录 `endpoint` 与 `playback_head`。两者用同一设备单调时钟，相减得到端点确认至首段播放头首次推进的估计，含约 10 ms 的播放头轮询粒度。听感另用成人观察或同一外部时基测说完至可闻声音。
- 第一个终端的服务器日志记录 `capture_sealed`、`asr_final`、`llm_first_approved_segment` 与 `tts_first_pcm`，使用相对于同轮连接的服务器单调时间，只在本机日志内求差。记录设备、系统、端点方式、轮次、值和异常，避免直接相减跨机时钟。
- 首段收齐且核对段号和样本数才播放。服务器一段开始合成时可继续有界读取 LLM 文本，第二段合成可以与手机播放上一段重叠。客户端没有帧级渐进播放，因此没有同段低水位策略。段尾缺失时该段不会开始播放，两段之间可有间隔，断流由既有超时处理。
- 首测按键开始、自动封口、两段顺序、播放中停止、等待回复时停止后马上重开、锁屏再解锁，另回归原有模拟功能。分别记录实际说完、端点和可闻响应，未实测项目标记未测。儿童录音及云测试留待单独放行。

## 服务器合成单次对照

同一北京候选模型的先前串行探针与本次逐句探针是两次独立实测。前者等 LLM 两段结束才开始 TTS，后者按已通过检查的短句启动 TTS，并有一个队列槽位和至多一个正在等待入队的句段。两段仍逐个合成和发送，手机播放上一段时可合成下一段。

| 服务器指标 | 原串行 | 逐句重叠 |
| --- | ---: | ---: |
| LLM 首完整段 / 流结束 | 533 / 559 ms | 619 / 644 ms |
| 回复首段 TTS 首 PCM / 收齐 | 556 / 1810 ms | 572 / 1775 ms |
| 调用 ASR 封口至可播放首段 | 3507 ms | 3549 ms |
| ASR 启动至两段结束 | 7644 ms | 7552 ms |

优化轮输入 TTS 预检 1960 ms，重采样校验共 2032 ms，单独计时。ASR 上行 59,520 字节且最终转写匹配，阶段 3289 ms，两段回复返回有效 24 kHz PCM。离线门闩复现慢后续 LLM 与首段 TTS 确实重叠。两次样本不足以判断提速，首段本次反而慢 42 ms。没有 OPPO 可闻数据。
