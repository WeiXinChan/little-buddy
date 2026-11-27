# 唯一隔离实际诊断（未部署）

冻结执行source `8e22de6bd01ddc9106c0fbe348e27c3b990afe41`，原始私密输出stage-probe-8e22de6b-once；result SHA256 `a544d5c3ebd1c1d66e3265731e8147a0f9cb15a038c9d01d8cf95b55fd39dddf`。按已有明确授权执行一次，不重跑。原始执行版本及结果不改。后续追加证据，并单独收紧非法observer返回应用Task的处理：只观察异常、不取消/等待该Task，防止诊断误取消语音。该非法observer分支未在真实轮使用；本轮不会为此再次云调用。

固定AIFF SHA/22050Hz/68097samples核对后仅一次重采样，16k为49413samples、98826bytes、SHA `db6dd2c7fa373f4b9d0b8304f1322158e57d66cc72436a53fce4125d810db69b`。实时节拍输入，不在手机播放。ASR empty=false、fixed_case_matches=true；未保存转写/提示词/回答/PCM。

终态reply_complete；worker_exit0、forced_exit=false，peer cleanup confirmed/pending0/quarantined=false；V2Speech release_failed=false、pending0、last confirmed=true/aborted=false。61音频块、244800字节、61模拟节拍ACK。退出后检查无本诊断进程，heavy.lock可取得；生产服务、手机、V1未操作。

实际调用：fun-asr-realtime1、deepseek-v4.1-flash-1017文本4（endpoint/PLAN/FACTS/whole各1，无retry/repair）、cosyvoice-v3-flash1。图片生成/图片审核/外图下载均0，compact实际调用0。LLM用量8079输入/81输出token，4请求usage均提供、missing0；ASR/TTS费用未由此表计量，账单与实时免费额度未知，无fallback。未独立审核回答正文，不把协议完成当全面语义验收。

同一worker monotonic：输入发送完成到首次音频接收3844.877ms，其中到seal1704.645ms、seal到接收2140.232ms。模拟首effective ACK比音频接收更晚且不是speaker证据。阶段表在actual-summary.json：

| 阶段 | 本次耗时ms | 解释 |
|---|---:|---|
| 输入结束→probe收到 |301.528|固定client 300ms策略+TLS调度，不是ASR|
| ASR resource进入 |251.627|含连接/供应商任务准备|
| finish发出→final |349.049|真实识别等待；转写只验证布尔|
| ASR final→退出确认 |151.460|原V2关闭语义，未并行化/放宽|
| endpoint |646.545|独立模型调用；其后距尾部已超过1s，无额外再等1s|
| PLAN |901.133|完整JSON及本地验证|
| FACTS |565.188|与PLAN重叠，不再相加|
| whole review |673.953|本次单句，无额外segment调用；无安全/quality拒绝|
| TTS open→connected |178.905|共享供应商mark仅在本V2显式作用域接收|
| connected→task_ready |56.619|task准备|
| resource_ready→firstPCM |312.954|真实首PCM等待|
| first→secondPCM |0.767|本次lookahead不是主要耗时|
| first_audio发送→client接收 |1.200|仅本机loopback TLS，不推算手机网络|

本次可证瓶颈是多段必要等待累计：输入侧ASR约0.60s+确认退出0.151s+endpoint0.647s（另含0.3s probe等待）；输出侧PLAN约0.901s+whole0.674s+TTS首PCM准备约0.55s。未出现重复识别、额外摘要、第二次规划或多句复审。ASR退出重叠即便可做，本样本收益最多约151ms，不能凭此解决2s中位数目标；root已决定暂不实施。后续需以这些阶段为依据选择业务优化，不能盲目删审核/改变端点语义。

计时限制必须保留：128条实际已达上限，truncated=true。首音之前及首次有效ACK完整；后续重复ACK/compact_skipped消耗记录，尾部tts_released/reply_end的**时间未观察**，不补造。reply_complete和清理来自独立终态/资源检查，不来自缺失尾部时间。progress.json有界结构化材料与全部原始JSON保留；不为补尾部再消耗云调用。同步progress落盘/计时本身有开销，未校准扣减。

这轮固定新空上下文、再生合成输入、模拟client，与code31手机当前上下文/硬件/声学输入不同。不能用3.845与7.233直接相减归因手机，也不能用一个接近4s样本认证P12 median/P95；更不能认证P15或speaker声压。根审后再决定有证据的优化或后续验证。
