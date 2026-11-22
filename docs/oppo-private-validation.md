# 成人 OPPO 私有联调

## 首次连接

依赖现有 Mac SSH 访问、Android Platform Tools、支持 USB 调试的 OPPO、服务端能执行 `sudo -n` 的授权维护账号。服务端已准备 30 天 localhost 开发证书与独立设备令牌。应用调试变体只对 localhost/127.0.0.1 增加系统用户 CA 信任，仍校验证书链和主机名。

1. 在 Mac 下载工单的两个 APK 和 `little-buddy-0.1.5-voice-lab-SHA256SUMS`。运行 `shasum -a 256 -c little-buddy-0.1.5-voice-lab-SHA256SUMS`。旧版已安装的同一 localhost 开发 CA 继续有效，无需重装。首次联调时，从 TITA-10 下载并核对 CA，再将 `little-buddy-loopback-ca.cer` 安装到 OPPO 的用户 CA 存储。安装菜单随 ColorOS 版本变化。只在本次测试设备安装，验收后移除。
2. 登录原服务器，切到本 PR 分支的仓库目录。约定两个终端。第一个从 Mac 启动有转发的 SSH 会话，服务器提示符内运行 `scripts/with-private-voice fake`。确认假服务后用 Ctrl+C 停止，再按同样方式运行 `scripts/with-private-voice dashscope`。每次服务只监听服务器 `127.0.0.1:8443`，20 分钟自动结束。

   ```bash
   ssh -t -o ExitOnForwardFailure=yes -L 127.0.0.1:8443:127.0.0.1:8443 <已有SSH目标>
   ```

   设备令牌由服务器管理员在无录制的受控 SSH 终端查看 `sudo -n cat /etc/little-buddy/voice/device-token`，仅填到手机密码栏。后台以 `LoadCredential` 加载。百炼 Key 由另一路凭证加载。
3. OPPO USB 连接 Mac，解锁并允许 USB 调试。在第二个 Mac 终端运行：

   ```bash
   adb devices
   adb install -r -g little-buddy-0.1.5-voice-lab-debug.apk
   adb reverse tcp:8443 tcp:8443
   adb install -r -t little-buddy-0.1.5-voice-lab-instrumentation.apk
   adb shell am instrument -w com.littlebuddy.sim.test/com.littlebuddy.SimUiRunner
   adb logcat -T 1 -v brief 'LittleBuddyVoice:D' '*:S' | tee little-buddy-timing.log
   ```

   多设备时给每条 adb 命令加 `-s <序列号>`。在「私有语音验证」输入 `wss://localhost:8443/v1/turn` 和设备令牌。点击开始，等待「正在听」，由成年测试者说已约定的短问候。先验假服务两段提示音，再验真实云回复。
4. 验收后 Ctrl+C 关闭服务器命令及 SSH 会话，运行 `adb reverse --remove tcp:8443` 并从 OPPO 移除测试 CA。这条隧道仅用于开发验收。

## 观测与验收

- Android 日志以每次私有连接生成的随机 `turn_id` 分组。录音和收包事件使用录音 `op_id`，每段播放事件使用对应播放 `op_id`，`segment=0` 表示轮级事件。记录只包括事件、编号和单调时间，不含语音、文本和令牌。
- 每轮录音封口时记录一次 `endpoint_confirmed`，在此之前若检测到语音，写出 `last_speech_detected` 的最后一个有效算法窗口时间。后者会受噪声、设备缓冲和算法影响。首段 `first_pcm_received` 给出端点到首 PCM。每段 `playback_requested` 对应请求启动 AudioTrack，`playback_head_first_advance` 记录播放头首次推进。首段附端点以及算法末语音至播放头的差值，后续段仅记录同段首 PCM 至播放头。播放头按约 5 ms 间隔轮询，实际说完至可闻仍由成人观察或同一外部时基测量。
- `turn_finished` 表示已校验全部段尾和整轮结束声明，且所有播放操作均完成清理。`turn_cancelled` 包括主动停止、失去前台、超时和错误，部分已播音频无法撤回。服务端事件（如 `capture_sealed`、`asr_final`、`llm_first_approved_segment`、`tts_first_pcm`）单独使用服务端单调时间。只在同一设备内求差。
- 旧版 0.1.4 收齐并核验整个 PCM 段才开始播放。新版 0.1.5 在首批已校验帧填满启动缓冲后开始播放，段尾仍核对累计样本数。Android 音频实现的启动参数默认 120 ms（约 2,880 帧），构造参数可在 40–300 ms 内调整。120 ms 用于吸收轻度抖动并早于正常整段到齐。API 31 及以上尽量采用所设帧数，较旧 Android 使用设备要求的有效缓冲容量。短段经段尾核验后可用静音补足启动水位，仅实际帧参与完成判定。
- 每段最多四个待消费 PCM 帧（每帧最多 6,400 字节），网络读取被限流，原生缓冲也有上限。短暂断供时设备可能输出静音，连续约 2 秒无写入或播放头进展会中止整轮并提示重试。乱序、缺帧、长度错误或控制帧提前结束也会取消并清空未播队列。原生释放完成前不会开始下一段或打开麦克风。后端已有首个有效 PCM 立即发送的路径，同时有界接收后续 LLM 文本。
- OPPO 旧版已通过私有假服务两段播放，并听到真实云问候回复。旧日志可辨认的端点至首播放为 2908、2738、3593、3600 ms，主观约 3 秒。旧版没有轮次和段号，且播放清理会重复记端点，这些数值只供定位。新版对照请记录逐轮首段数据。先测假服务两段、等待时停止后重开、播放中停止、锁屏再解锁和原模拟流程，再测真实短问候。音频断供、恢复、音量突变和实际可闻时延均留待真机观察。儿童录音及云测试留待单独放行。

## 服务器合成单次对照

同一北京候选模型的先前串行探针与本次逐句探针是两次独立实测。前者等 LLM 两段结束才开始 TTS，后者按已通过检查的短句启动 TTS，并有一个队列槽位和至多一个正在等待入队的句段。两段仍逐个合成和发送，手机播放上一段时可合成下一段。

| 服务器指标 | 原串行 | 逐句重叠 |
| --- | ---: | ---: |
| LLM 首完整段 / 流结束 | 533 / 559 ms | 619 / 644 ms |
| 回复首段 TTS 首 PCM / 收齐 | 556 / 1810 ms | 572 / 1775 ms |
| 调用 ASR 封口至可播放首段 | 3507 ms | 3549 ms |
| ASR 启动至两段结束 | 7644 ms | 7552 ms |

优化轮输入 TTS 预检 1960 ms，重采样校验共 2032 ms，单独计时。ASR 上行 59,520 字节且最终转写匹配，阶段 3289 ms，两段回复返回有效 24 kHz PCM。离线门闩复现慢后续 LLM 与首段 TTS 确实重叠。两次样本不足以判断提速，首段本次反而慢 42 ms。该表只包含服务器数据。
