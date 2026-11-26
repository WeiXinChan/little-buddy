## 固定多轮验证准备：A03/A04/P12/P15

基线 main 9dd265e7；本批仅验证工具/合成案例，不改生产行为，不执行云。

### 已有证据及准确接口

root 的 qwen4-max-plan-live-probe.json/probe-qwen4-plan.py 已只读核对：4个各自新建Session的单轮裸PLAN，附逐句safe，共16模型请求；7326/7802/8145/9250ms。未调用VoicePeer事实提取、整段审核、TTS、ACK及多轮状态提交。原报告与脚本不修改，不能推导A03/A04/P12通过。

可复用路径：backend/v2/voice.py 的 respond/_respond → compact_memory → read_request(plan) → read_request(facts) → Session.record_input → review(整段) → planned中的逐句review → providers.synthesize → audio → Session.send/pending → Session.ack → game/roles/rules/secrets/heard提交 → reply_end。backend/v2/companion.py 的 UnifiedProviders.plan/facts/safe/compact 与 DashScopeModel.complete 为既有生产实现，TEXT_MODEL仍qwen4-max。Session.context()仅从实际输入证据/已播材料组装。工具不得从expect向context补写mode、规则、角色或heard。

### 可执行入口及层次

离线清单：`python3 -m scripts.v2_multiturn_probe --list`。
离线入口边界测试：`python3 -m unittest tests.v2.test_multiturn_probe -v`。

后续root审核授权后，由其既有受控环境构造生产 `UnifiedProviders`（真实qwen4-max与speech），仅选择一个case调用 `await run_case(case, providers)`；函数不读取配置/凭据，不提供自动live CLI，provider及HTTP资源由root持有并清理。其dynamic_images必须为None，且不协商图片能力，禁止本验证生成图片。root须独占该provider实例，函数临时包裹model/speech计数，finally恢复，不并行复用。完整case只运行3轮；调用一次不遍历目录。

入口从**合成完整表达文本**调用实际VoicePeer.respond，正常bind媒体scope、模拟准确player/stream/segment/end ACK，连续复用同一Session。保留生产PLAN/facts/safe/TTS/预算/交付提交，不手工提交预期状态。未经过真实ASR、endpoint完整表达检测、私有TLS/WebSocket、手机播音/播放头/声学；ACK为模拟接受，不是已听证明。本批offline tests的model/TTS也为合成替身，只证明harness可运行且能发现故障，不证明qwen4玩法质量。

### 案例和必要判定

cases.json为12案例/36轮：四玩法各2主题及不同措辞，每例3轮；另4例覆盖猜谜转故事、交换出题、修改规则、明确放弃。每个标签/输入/expect固定可hash。expected字段仅供出端判定，绝不传provider。

判定来自真实Session提交后的game、规则/角色关键词、实际heard变化、reply_end与failure状态。错mode、丢规则/角色关键词、放弃仍留原玩法、审核拒绝、丢失已播上下文均可标红并立即停止该case，不重试刷结果。它们是必要条件，不是充分语义评分；角色关键词同时出现不证明角色归属/交换正确，heard变化不证明回答相关，轮流规则存在不证明实际轮换正确。root首批须在内存中检查实际响应的角色归属、轮换/不重复、改规则生效及谜底/私事隔离；结果只落判定/标签，不存响应正文。不把仅结构PASS扩大为A03/A04通过。当前准备未提供自动语义裁判，未增加第二模型评分或预设玩法逻辑。

可用 `await run_case(case, providers, observer=observe)` 同步观察：`observe(label, snapshot)` 接收该轮实际交付后context的深拷贝只读快照（dict递归MappingProxyType，序列tuple），含必要game/heard/事实/私事/未播谜底供固定合成案例的内存语义检查；不含Session/provider/PCM/expected，不修改真实Session或ACK。默认observer=None，不落正文或secret。观察者禁止调用模型、持久化材料或更改ACK；入口不给其provider引用。异常会停止并追加batch-stop failure、finally清理，不吞作PASS；async回调被拒绝。root可在同步回调内检查角色归属/轮换后仅保存布尔结果；不必修改harness。

建议执行顺序：先guess-animal单例3轮，检查角色互换、未播谜底与交付上下文；再story-moon；再按root结果逐例批准剩余，不一口气跑36轮。任一质量/供应商/预算失败立即停批，不自动重试整批。生产read_request的原有有界retry仍计入同一模型请求门限，不放宽安全审核。

### 请求及费用上界

单例硬门限：总45秒；最多24个底层model.complete（含plan/facts/safe/compact和生产读重试），每次发出前data及instruction各≤32768 UTF8 bytes；生产单次max_tokens仍1400，故输出token请求上限33600。最多12次TTS、总1440 Unicode字符（汉字计2时最多2880计费字符的参考量；不能当真实账单）。这些是安全天花板，不是建议用尽的额度；无图/无ASR。

通常每轮1 PLAN+1 FACTS+1整段审核+0或2–4逐句审核，三轮约9–21模型调用、3–12 TTS；compact/retry占剩余24门限，超限即停。最大输入token不能从字符简单等同，需root使用当前供应商tokenizer/账单计量；本入口没有完整HTTP费用拦截或可信货币上限，root已有现有服务必要验证授权，将按当前qwen4-max单价及单例usage差值选择有限支出；请求前保守预留/剩余额度可由root外围受控provider拦截，不需重复向用户索取抽象云调用许可。不拿旧qwen3.8价估qwen4-max。预算目标约3元/有效互动小时继续OPEN。

### P12/P15输出与剩余证明

输出只有合成标签、case hash、布尔判定、阶段耗时、调用数、单例执行前后usage差值白名单（含missingusage时该token量为null，未知不当0）、字符量及固定错误类；不落输入/模型正文、PCM、scope身份、secret、signed URL。Stage计时区分plan/facts/safe/compact；整轮first_audio_after_text_ms仅**合成文本边界→第一传输音频**，不是有效音频或完整表达结束→真实播出。严禁占位语/固定降级句当有效音频。P12字段固定false；后续需root真实TLS/ASR/TTS/播放链路标记完整表达结束与首个语义有效可听音频，汇总median≤2s/P95≤4s及样本数/失败/超时/被取消分母，思考时间单列，保留不达标原结果。

P15字段固定false：现报告只含模型usage与TTS文本量，不含真实ASR重复probe上传、图片两道审核/生成、长会话摘要/取消/重试的完整成本。有效互动时长、当前真实价格与供应商账单须集中最终验证；免费图片20张不能证明长期3元/小时。不改设备、供应商、生产配置/部署，不调用云，不重跑旧全集。Android ONNX probe与锁屏/owner延期仍各自独立。
