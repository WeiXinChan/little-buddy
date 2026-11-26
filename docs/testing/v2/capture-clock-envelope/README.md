# 有界时间戳估计模型（待硬件生产探针确认）

本批是基于一次 OPPO 3.5s metadata 的可审生产修复。原 code20 启动FAIL、code21 rate FAIL、PR83 工具截止FAIL全部保留；本地 trace 重放不等于设备生产PASS，更不证明60min录音。

## 事实与有限假设

原始151条唯一frame/ns已随测试保存（JSON、由JSON精确导出的TSV、SHA256）。相邻旧判据拒绝37次，首末53440frames/3340156385ns约15999.250885Hz；同会话所有>=500ms pair共8162个（高度相关的配对，不是独立样本），原15984–16016Hz与±2frame判据0拒绝。100/200/250ms仍41/10/5拒绝。相对16k首pair残差摆幅690154ns。这支持研究短时估计相位与长期采样率的区别，不能证明硬件提供任意固定误差保证。

[官方 AudioTimestamp](https://developer.android.com/reference/android/media/AudioTimestamp) 定义 nanoTime 为 estimated capture time；没有短对±2frame精度保证。[历史 Android11 CTS](https://android.googlesource.com/platform/cts/+/android11-release/tests/tests/media/src/android/media/cts/AudioHelper.java) 区分jitter与长期检查，不作为OPPO保证，不复制其毫秒级容差。

本实现显式选用 **每个估计±500us** 的有限模型预算，整个相位可行区间不超过1ms：预算总跨度取现有软件单调时钟的一个1ms分辨单元，另行保留该时钟本身完整1ms量化误差。它不是将实测690154ns当厂商保证，也不是调大长期rate或2frame参数；实测轨迹是对候选模型的一个一致性检查。这个工程预算仅有一次3.5s支持，仍须root/QA批准以及匹配新版生产探针；不足则failclosed，不能自动增大预算或退回软件时间。真实clock若违反假设、但仍伪装成模型内轨迹，软件不能证明硬件诚实。

## 每一条观测都参与，不等500ms才鉴权

对frame F的真实capture时刻T(F)，要求有一条速率始终在15984–16016Hz的可行时钟路径，且T(F)位于估计S的[S−500us,S+500us]。对每个严格前进的硬件frame，沿上一可行区间传播：

```
lo' = max(S'-E, lo + floor((F'-F)*1e9/16016))
hi' = min(S'+E, hi + ceil ((F'-F)*1e9/15984))
```

空交集立即拒绝；没有重置区间来接纳新观测。整数向外取整保守，每次仍被±500us观测区间夹住，不会累计成无界时间误差。原frame/time回退、stationary frame换time、future/陈旧stamp、mono/boot桥异常、JNI耗时计入检查全部保留。

此外，对 **所有** 相隔至少500ms的原始stamp pair继续执行原15984–16016Hz、±2frame判据，绝不添加相位预算到这个长期判据。不是只比较首pair或单一滚动锚。实现将相对固定首pair的 `F*1e9-S*15984` 最大值、`F*1e9-S*16016` 最小值聚合，等价检查所有已满500ms的历史pair。待满500ms队列最多8192点（0.5s在rate/phase模型内至多约8025个不同前进frame），超出也拒绝；成熟极值永久保留、不定期重置累计原点。累计计数、range检查不变。

首次可信硬件pair约150ms时就建立有限区间；原startup仍需两个正且前进的pair、原点证明及native连续性证明，并维持固定500ms/8000samples。短窗阶段由可行区间约束，不是无检查通行。真实trace重放在166ms锚定。CaptureBootstrap、原sample0、prefix replay cursor、KWS首字、取消立即清零均沿用，不在第一stamp将origin或readcount归零，不上传未锚定PCM。

## 误差必须花掉预算

记最新硬件frame为F；资源预算始终使用保守外界 `lo = S−500us`。即使历史可行区间收窄，也不返还phase预算。软件mono读数是floor毫秒，因此当前最晚时刻取 `(monoMs+1)*1e6`：

```
producedUpper = F + ceil(max(0, nowUpper - lo)*16016/1e9)
unreadUpper   = max(0, producedUpper - cumulativeRead)
roomFrames    = capacity - 320 - unreadUpper
```

仍是原native buffer（申请6400bytes、对应3200frames；没有增加buffer）。phase和mono量化共同使新观测最多比无误差stamp多计约25个当前生产样本；这会减小room，不赠送320 reserve。JNI/read/owner/KWS等待仍从累计read与实际时间中扣，不每轮刷新完整native预算。只有原startup最多500ms尚无stamp时使用既有有界软件upper，后续不作无限fallback。

对sample坐标p，保守最早时刻使用 `lo + floor((p-F)*1e9/rate)`，过去坐标rate=15984、未来坐标rate=16016，再用既有BOOT/MONO桥和保守−1ms取整。phase只使sampleTime更早，队列age更老；`durationMs`仍取15984下界。年龄也按 `nowUpper-lo` 检查原100ms上限（不放宽）。所有prefix和队列仍使用原坐标，sample0不改名，过去音频不能靠重标变新。

## 实际检查与边界

```
scripts/with-build-lock python3 scripts/test-v2-capture-clock.py
scripts/with-build-lock python3 scripts/test-v2-capture.py
scripts/with-build-lock python3 app/src/androidTest/run-native-probe-regression.py
```

新clock检查包含原始151条JSON/TSV一致性与真实production ledger重放；有限相位抖动、持续正/负drift（含±1100/±1250ppm近界，±1000ppm边界仍允许）、突然跳变、逐步超界走偏、非首pair长期反例、误差花room/earliest sampleTime、缺失/陈旧与回退。Capture受控回归继续包含连续生产静默覆盖/单次小于buffer但累计超界、21/50帧、原首字坐标、prefix取消清零及真实Sherpa实现（受控ONNX端口）。不以受控输入证明真实童声或物理连续性。

原诊断 `rawRc7PairFailsUnchangedProductionLedgerAndExactOldOracle` 的断言未削弱：它明确编译使用5318d85历史ledger快照（只改类名、复用同CaptureStamp），继续验证原失败。新模型另用完整真实trace验证，避免把旧FAIL改写为PASS。旧room单测169ms变为168ms是误差预算的更严格推导，首次失败日志保留。

本轮只编译Android主/测试Kotlin，不生成或冻结业务APK、不给版本加号。NativeTimestampTest同生产Capture使用target NativeReadLedger/CaptureBootstrap，并输出运行时 `clockModel()` 身份。**旧code21 target没有新算法/该方法，单独更新testAPK不能验证此修复**；root审过后必须从匹配新main统一freeze业务与testAPK，再跑真正生产路径探针。本轮未安装、未联系Mac/其他agent、未云调用；模型配置不在改动范围。
