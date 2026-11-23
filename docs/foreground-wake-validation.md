# 前台唤醒与首指令验证

TITA-42 基于 `main@cb208b45`。装有配套后端的正式入口在配置后请求麦克风权限，亮屏前台开启本地唤醒。「开始猜动物」保留手动直达。唤醒单独出现时，先归还录音资源，再播本地「宝宝，我在。」。播放资源归还后自动听，收到有效语音才连服务。自动听 12 秒无有效语音时恢复等待唤醒。

紧接指令沿用同一个 16 kHz `AudioRecord`。模型尾词时间戳加 120 ms 估算唤醒词尾，在此后最多观察 500 ms。首指令从估算边界往前 160 ms 回读，和实时流一起按样本顺序送进同一队列。新鲜会话通过 `session.start.wake=true` 取得零段聊天许可，待 `turn.ready` 才发送 PCM，后端仅清理首转写开头精确匹配的唤醒语。准备期间最多排队 80,000 个样本。结束等待麦克风释放及 ready，统一发送一次结束和总样本数。缺失配套后端的非空首回复被拒绝。旧客户端可继续使用配套新后端的原路径。

待机与单独唤醒回应期间无 WebSocket 或 PCM 上行。后台、锁屏和停止撤销上一代的上传许可，清空积压并回收设备句柄。停止后回到等待唤醒。应用层索引仅验证 `AudioRecord` 成功交付的样本连续性，硬件采集丢帧仍需真机观测。声学尾部估算如果偏差较大，可能残留部分唤醒词或误判紧接指令。

## 固定依赖

- CPU AAR `1.12.27` 原始发布文件。SHA-256 `ef0466b4e66fa950e7f5a395e69dbe1a54c9f6425c73c724474e195e2b676e3c`。[SDK 发布](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v1.12.27)
- 中英 Zipformer `sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20` 的 `epoch-13-avg-2-chunk-16-left-64`。原始归档 SHA-256 `68447f4fbc67e70eee3a93961f36e81e98f47aef73ce7e7ca00885c6cd3616a6`。INT8 encoder 与 joiner，FP32 decoder。核对词表 ID `w=178, ǎ=245, l=129, ì=203`。[模型发布](https://github.com/k2-fsa/sherpa-onnx/releases/tag/kws-models) · [权重许可](https://github.com/k2-fsa/sherpa-onnx/issues/3802)
- Release 只打包 arm64-v8a，Debug 保留 x86_64 等调试 ABI。JNI 与 ONNX Runtime 1.17.1 的 arm64 ELF 段均显示 `0x4000` 对齐。APK 包内附 Apache-2.0、ONNX Runtime MIT 与其第三方声明。APK 路径和设备实测另见验证记录。

| 实际打包文件 | SHA-256 |
| --- | --- |
| decoder ONNX | `63a22dd60f40fff082ac3e09afa507f6787da36df76ded2fbe145fa233e22c21` |
| encoder INT8 ONNX | `408bbd740838c42d5bf6d1c5b80b3c88b616c7860b92d980328b5b068c76ae48` |
| joiner INT8 ONNX | `190d4067b4cc20b72a42a1916e69d92052000fb7051a427ebb1bc72a69207dc1` |
| tokens.txt | `2d3f32311f9b692b964da3c90e830258d3e78e013cb0c992dbfb15cd5a1a71b0` |
| keywords.txt | `d6ca8e845963fa305acd3599e2eac5de3c9c734faad914413f583c19a55d1d98` |
| prompt.pcm | `90eac1536ac74f27a1a9e9983d0db781097f97342c037d68cf9840d84f0b6a3f` |

## 本地回应素材

通过既有北京百炼语音推理 API 生成一次「宝宝，我在。」。参数为 `cosyvoice-v3-flash`、系统音色 `longanyang`、PlainText、无 SSML、24 kHz 单声道 PCM16LE，使用默认韵律参数。响应原样打包 96,960 字节，2.02 秒，实测峰值 −3.9 dBFS。凭证只由临时非 root systemd 单元读取。素材为 AI 生成音频，依账号既有百炼协议用于本项目。仓库同时保留适用条款入口，后续分发按协议及对应场景的合成标识要求处理。听感留在最终 APK 验收。[合成 API 与系统音色](https://help.aliyun.com/zh/model-studio/realtime-tts-user-guide) · [阿里云产品服务协议](https://terms.aliyun.com/legal-agreement/terms/suit_bu1_ali_cloud/suit_bu1_ali_cloud201802281451_77479.html)

## 合成模型回放

用 eSpeak NG 1.51 的 `cmn-latn-pinyin` 音色，语速 150、音高 50、幅度 100。显式输入拼音，避免 `cmn` 把部分拼音按英语发音。FFmpeg 6.1.1 转 16 kHz 单声道 PCM16LE，裁掉首尾振幅不超过 327 的样本，加 500 ms 前静音和 2 s 后静音。语料在本地生成。测试合成音频没有打包。

`scripts/test-wake-model.py` 使用 Python 3.12、sherpa-onnx 1.12.27 和 NumPy 2.5.5。脚本打印每条 PCM 哈希和首次检测位置。当前默认 score 1.5、threshold 0.25、2 个 trailing blank。13 条合成样本中，正例 **8/8** 命中一次，反例 **4/5** 拒绝。「瓦力玛丽」误唤醒一次。阈值提高到 0.35、0.45 仍有该误报，提高到 0.60 时原六条正例均漏掉，且仍有误报，因此保留默认参数。10/20 dB 白噪混合的两条正例由固定种子生成。样本规模只支持冒烟结果，童声召回、噪声泛化和误唤醒每小时留给设备测量。

脚本因已知误报返回非零。用 `--fixtures <目录>` 可保留合成 PCM 与命中点。把该目录传给 `LITTLE_BUDDY_WAKE_FIXTURES` 后，JVM 测试用实际模型命中时间驱动 Kotlin 采样流，检查连续采集、单独回应分类及上传片段顺序。常规 JVM 测试另有短读、环缓冲回绕和待机零可上传帧。设备 CI 保留原 21 项，并加入 JNI 资产加载和静音检查、ready 前后封口及取消后的待发数据丢弃。

## 本地构建记录

Gradle 8.13、JDK 17、Android SDK 36、Build Tools 35.0.0。同工具链下原始未签名 Release 为 1,134,967 字节，本阶段为 26,300,340 字节，增加 25,165,373 字节（24.00 MiB）。其中唤醒 assets 压缩后 4,161,091 字节，两个 arm64 原生库合计 20,871,056 字节。APK 只有 arm64-v8a。Build Tools 的 `zipalign -c -P 16 4` 检查通过。

后端 69/69。Debug、Android 测试 APK、未签名 Release 构建通过。3 个新增 JVM 测试通过，其中合成回放的独占样本区间逐样本相等。连续句、分句零间隔、120 ms 和 300 ms 停顿均走同流；单独唤醒和 750 ms 间隔走回应分支。零间隔及两条短停顿样本的回读起点覆盖程序记录的指令起点。首字能否真实转写、锁屏后设备行为、扬声器音质、OPPO 上的唤醒延迟和误报仍待设备验证。设备用例运行以 PR 的模拟器 CI 结果为准。

## TITA-50 复验输入与剩余边界

上传环缓冲保留最多 80,000 个样本，并把短读合并为 320 样本的线上包。仅封口允许短包。WebSocket 预算为 161,500 字节，等于 250 个最大包（含每包 6 字节头）。发送前检查加入本包后的队列长度。主线程每次最多排送 16 包，队列满时以 20 ms 间隔检查，连续阻塞 2 秒即撤销采集代。封口沿相同队列等待剩余数据依序排送和结束包的空间。旧代取消会移除排送回调、擦除未送样本并取消 WebSocket。

设备回归新增容量和取消检查，并用正式 BuddyActivity、Android 真实录放句柄、Sherpa JNI 和回环 TLS 假 ASR 串接。测试在 AudioRecord 读返回后替换样本值，保留读长度和实际资源生命周期。假 ASR 比对完整「玩猜动物」音频及它所在的逐字节连续区间。用例覆盖待机、单独回应、续听、停止、退后台和设备睡眠。Android 设备执行结果以当前 PR 的 CI 为准。测试 APK 中三段 PCM 直接取自以下命令生成的对应文件。AAPT 会把以 .gz 结尾的资产解压并去掉后缀，旧 CI 以 .gz 路径打开导致失败。现在源码、APK 条目与 AssetManager 统一使用 .pcm，CI 与 OPPO 入口都预检逐文件哈希。正式 APK 不含测试语料。

```bash
python3 scripts/test-wake-model.py --fixtures /path/to/fixtures
python3 scripts/compare-wake-models.py /path/to/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01
```

WenetSpeech 对照用官方归档，SHA-256 `b2f7c89690dc8ce4c6ed6afeab7cd800c36ad1421fb6b6302b4a4b194cf7f35f`，使用 epoch 12 的三个 INT8 图和同包 tokens。两组使用同一固定参数。验证集变更了语速、音高、指令和近音组合，仍由同一合成器产生。脚本逐条输出哈希和检测索引。

| 候选 | 调参集正例 | 调参集反例 | 验证集正例 | 验证集反例 |
| --- | --- | --- | --- | --- |
| 中英现用 | 6/6 | 3/4 | 4/4 | 3/5 |
| WenetSpeech | 4/6 | 4/4 | 2/4 | 3/5 |

中英在调参集误报「瓦力玛丽」，在验证集误报 `wa3 li4 fa3 li4` 和 `wa3 li4 wa3 ni4`。WenetSpeech 在验证集误报 `wa3 li4 na3 li4` 和 `wa3 li4 wa3 ni4`。两者均命中同音文本边界样本，统计排除该样本。保留现用模型作为本 PR 的复核基线，因为对照降低了召回且未改善独立验证集拒绝率。真实童声、音量距离和环境噪声仍待验收。

### 百炼素材使用证据

现有账号通过北京业务空间的已配 CosyVoice 推理 API 产生该片段。生成链路没有调用控制台体验入口、声音克隆或第三方音色。产品服务协议第 85.1 条指向百炼专门协议。专门协议将 API 集成纳入适用范围，并要求使用方对输出商业化、第三方权利及合成标识承担责任。体验条款对体验输出的分发另有限制，其范围为体验入口。当前服务器能核验推理配置和已生成素材，缺少该账号的订购单和可能覆盖公开再分发的补充条款，公开分发权利仍待账号持有人核对。包内已保留来源、参数与合成音标识说明。 [产品服务协议](https://terms.aliyun.com/legal-agreement/terms/suit_bu1_ali_cloud/suit_bu1_ali_cloud201802281451_77479.html) · [百炼服务协议](https://terms.alicdn.com/legal-agreement/terms/common_platform_service/20230728213935489/20230728213935489.html) · [体验功能特别说明](https://terms.alicdn.com/legal-agreement/terms/common_platform_service/20260716114753386/20260716114753386.html)

## 家庭素材与公开构建隔离

家庭包仍要求清晰温暖的「宝宝，我在。」。后续源码从 `main` assets 移除百炼 PCM，现有账号的原始合成素材保存在服务器受控输入。现用素材 SHA-256 为 `90eac1536ac74f27a1a9e9983d0db781097f97342c037d68cf9840d84f0b6a3f`。公开源码与公开 CI 自本变更起停止新增该素材。此前的 Git 历史与第三方缓存仍可能保留旧副本。

家庭签名保管人先在受限服务器核对签名环境，用新建的私有检出和 `umask 077` 构建，再按既定流程签名。应在签名后从 APK 提取 `assets/wake/prompt.pcm` 并复核上述哈希，以及已登记的证书和应用 ID。Release 生成任务在输入未指定、文件在仓库内或者大小／SHA-256 不符时失败。在已授权的签名环境中执行下列命令，发布签名由签名保管人单独处理。

```bash
umask 077
scripts/with-build-lock env LITTLE_BUDDY_FAMILY_PROMPT=/srv/little-buddy-private/wake/prompt.pcm \
    ./gradlew --no-daemon :app:assembleRelease
unzip -p app/build/outputs/apk/release/app-release-unsigned.apk assets/wake/prompt.pcm | sha256sum
```

公开 CI 编译 `ciRelease`，其包名为 `com.littlebuddy.sim.ci`。Debug 和 `ciRelease` 使用工程生成的两段正弦音，CC0-1.0。家庭 Release 仅从独立生成目录读取已校验 PCM。OPPO 工程探针使用可分发测试音，家庭暖声听感保留给成品验收。
