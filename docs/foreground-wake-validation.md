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
