# 固定合成 ASR 配对测量：交 root 审查，未执行云请求

工具 `scripts/v2_asr_pair.py` 默认 disabled。只用于同一既有合成 fixture，不能传音频、文本、模型、URL或密钥参数。生产依赖固定 `7b421b17f03399250b8dcc9b1bd781f782141f5e`，使用原 V2Speech 连接/释放、SpeechTask 验证和 Recognition 有界结果读取。没有修改 voice、供应商适配器或部署。工具源码另用冻结提交 `--tool-source` 精确比对，不把工具自己的SHA嵌入自身。生产 ASR 配置必须等于 fun-asr-realtime；其余现生产配置原样读取，不发任何 text/TTS/image 调用。

fixture固定为 `/home/ubuntu/tech/v2-delivery/performance-aiff-private/ordinary-introduction-16k.wav`，文件SHA256 `0ce8f590d98384383fab2d6004ae206a30f34d20c19372a34c48c0bfcf160801`。只读此精确文件，校验16kHz/mono/PCM16LE/49413 samples，精确时长3.0883125s。已知本地合成参考“你好，请用一句话介绍你自己”。不使用家庭录音、不生成素材，PCM不提交仓库。

## 公平性与事件定义

old：从fixture采集origin等待完整表达时长+300ms quiet后，才建连/start、按原6400bytes上限完整快照写入并finish。new：在同一表达origin发起建连/start，块末sampleoffset/16000决定该块最早可发送时点；ready晚时已available积压可立即依序补送，新块等待其原始采集时点。不改origin，不发送未来PCM，不为积压人为追加重放延迟。两者均在原表达结束+300ms之后且全部N字节flush完成才finish。每个成功任务恰1start+1finish；失败可以没有finish，不为凑计数补发请求。old失败、文本参考完整性不同或资源释放未确认时不执行new，不重跑old，不retry/fallback。new文本不同即停、输出差异布尔而不推荐产品重构。

每个trial独立Linux monotonic origin，所有时间以该trial固定表达结束为0，单位ms；captureorigin为负3088.3125ms、expression_end=0。open为连接尝试前，ready为task-started后，firstwrite为首块发送调用前、lastwrite为末块发送调用完成后，finish为持久化计数后finish-task发送调用前，final为完整task-finished文本返回，released为退出确认完成（未确认则null），release_checked仅为清理检查时点。`final`本身即说完→final；`finish_to_final`单独记录。均不跨机/跨trial绝对时钟相减。单对只评估建连/输送/可重叠计算，不能称phone/P12/p95/童声质量。

## 硬预算、输出与监督

最多2次socket尝试/2个ASR任务，old/new各最多1，严格串行，text/tts/image0。连接尝试、run-task和finish-task分别在I/O前写入计数，0600临时文件fsync→原子替换→目录fsync；落盘失败不发I/O。上限与实际使用分开。任务ID只在内存匹配，不写转写、错误正文、URL/key、原始taskid或PCM。文本仅内存比较，输出sha256/length/reference_normalizedeq及old/new equal/normalizedeq；hash不是语音质量证据。usage仅取固定数值字段duration/seconds/audio_duration/characters的最终值和最大累计值，未知保留空映射，不相加，不假定单位/价格/免费额度；quota或任何异常直接停止，无fallback。

pair worker总预算19s，每任务另有18s上限，取消后仅一个0.5s绝对收尾窗口；正常 V2Speech close 原0.35s释放逻辑不改。父20s监督，必要TERM/KILL各最多1s。forced_exit不能算cleanup_confirmed。run-owned进程必须全部回收，不后台运行。父子均核真实little-buddy-build cgroup、MemoryMax2GB/Swap0、root保护目录内heavy.lock被外部wrapper持有，子另核父PID/starttime/cgroup；不依赖systemd-run继承FD9，不修改wrapper。输出目录独占创建0700，所有结果0600，已存在目录拒绝，因此不能用同目录重做。父supervisor保存退出/强杀/实际结果文件SHA及清理状态。

以下命令均从该PR检出目录执行。TOOL_SHA用交付评论的固定工具head；prepare/smoke/once必须各用全新目录。当前只允许前两条零云命令；最后一条仅由root评审后明确放行并亲自执行，作者本轮禁止执行。

```sh
sudo -n python3 -I -B scripts/v2_asr_pair.py --prepare --tool-source TOOL_SHA --output /home/ubuntu/tech/v2-delivery/asr-pair-prepare-TOOL_SHA
sudo -n scripts/with-build-lock python3 -I -B scripts/v2_asr_pair.py --admission-smoke --tool-source TOOL_SHA --output /home/ubuntu/tech/v2-delivery/asr-pair-admission-TOOL_SHA
# 仅 root 未来放行，不是本轮操作：
sudo -n scripts/with-build-lock python3 -I -B scripts/v2_asr_pair.py --execute --tool-source TOOL_SHA --output /home/ubuntu/tech/v2-delivery/asr-pair-once-TOOL_SHA
```

prepare只读配置/固定fixture，不读key/不联网；smoke不读配置、key、fixture，不进入execute；真实原wrapper下验证父子准入。pureoffline测试不证明云任务接受节奏、完整性、价格和真实收益。24项验证中16项工具（含实际PairSpeech/Recognition本地假socket协议）、8项原V2Speech释放；首轮存在测试小数舍入断言失败（0.0005ms），修改断言容差0.001ms，保留原日志，未改任何生产时间。

## whole + first segment 审核并行：只设计，不实施

源码 `voice.py:1192` whole审核后，`1243` 多句第一句segment审核才到TTS；在相同played-only context下，两项无内容依赖，**多句**可并行原有两次review，join两项都允许后才进入TTS。正常成功路径调用数不增加，单句仍只有whole；但拒绝路径原先whole拒绝就不会调用first，新并行会已花费first请求，必须如实记录这种失败路径额外调用，不能说所有路径调用数绝对不增。如果“任何失败路径也不得多请求”是硬约束，就不能采用此推测并行。

不能直接并发调用现review：它会在内部重新取context。最小候选patch需冻结一次context，保证whole与first使用相同快照，将已通过的first结果只消费一次。缓存键必须包含session对象/ID、connection/turn/epoch/revision/output/private、上下文版本或快照摘要、精确whole/first文本及审核配置；任何scope/已播context变化使缓存失效。join前后仍核当前Operation/private/output及上下文相等，变化时丢弃、不复用旧结果，不以旧审核授权新context。新输入/取消/管理/生命周期退出/route/TTL过期同现有撤销；无新deadline、不commit。拒绝/异常取消另一项并在原有有界收尾内退出，不能先开TTS再等whole；后续句仍在原位置投影当时played context审核。单句不加first；不提前发TTS，不绕过segment/whole，不新增wire。

若whole耗时W、first耗时F，成功多句的这段可由W+F趋向max(W,F)，最多节省min(W,F)，而非固定650ms。ASR方案可能作用于普通表达，但复杂度涉及跨revision/lease；审核方案修改集中、收益只在多句且耗时真实时存在。code34没有sentencecount，不知道是否命中；旧8e22仅endpoint/plan/facts/whole四次text，是单句边界，不能拿来承诺first收益。下一数字phaseprobe只需在现有root唯一允许的整体请求中记sentence_count、whole/first起止/结果enum、TTS首PCM、取消释放时长；不为测阶段额外发review。此次ASR-only不发review，也不能回答该段实际贡献。

## 修正20s raw lease的产品契约

20s仅为未来raw资源租约上限，不能增加合法长思考失败或改变原capture容量；到期使raw lease失效并有界退出，保留原完整capture/原deadline/合法THINKING规则，后续真实正常probe用完整快照重新分析。只在该probe需要时建连，不按每revision重建，不截断回答，不延长deadline、不自动失败retry。若原资源未释放则quarantine，不能并行另开。此为产品设计修正，此工具没有实施lease。

code33第二SERVERVOICE根因和root局部提示phone未覆盖仍OPEN；本轮不触碰手机，不拿mock或两次成功关闭历史失败。
