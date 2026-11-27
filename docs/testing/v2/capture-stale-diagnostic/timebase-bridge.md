本次是PR147的增量时基取样修复，不是code24真机故障已修好。code24/source053c8c1/SHA6325584原件及真机失败保留，不制作或安装新APK，不改变code、后端、V1或时钟模型数值。

事实与未证：真实当前activity1/transport0/capture1在READY约306秒后于PRE_ROOM报TIMEBASE_CHANGED，bridge9ms、raw age11.407681ms、API跨度0ms、取消false/允许true，随后完整stop/release/join。两次明确RECORD_AUDIO running=false，因此当前已停止；不把package任意running正则当录音证据。旧实现init boot→mono，refresh mono→boot，点差包含两端调度窗口；旧日志无boot前后mono，不能判定本次是真suspend或伪漂移。时钟没有漂移而单次boot调用期间进程推进9ms的可运行反例，原053c生产ledger真实失败；初次测试harness漏编类单列，不算产品反例。

语义来源：[Android SystemClock](https://developer.android.com/reference/android/os/SystemClock)区分包含深睡的elapsedRealtime和不包含深睡的monotonic；[AudioTimestamp](https://developer.android.com/reference/android/media/AudioTimestamp)的时间为估计值，本实现仍使用TIMEBASE_MONOTONIC。[AOSP SystemClock实现](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libutils/SystemClock.cpp)读取CLOCK_BOOTTIME并转换为ms，[Timers实现](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libutils/Timers.cpp)将SYSTEM_TIME_MONOTONIC映射到CLOCK_MONOTONIC；这是所核AOSP实现，不是OPPO内核精度/调度保证。此修复不赋予硬件任何精度保证。

取样契约与推导：

- 顺序读MONOTONIC floor-ms m0、BOOT floor-ms b、MONOTONIC floor-ms m1。假设每个clock read正确、同钟不回退，则boot调用时mono属于[m0,m1+1)，boot属于[b,b+1)，真实offset属于[b-m1-1,b-m0+1]。两端1ms来自floor量化，不是新增容差。
- 初始括区间O固定，不随着检查重置。初始窗口宽度<=3ms（两个量化bin+最多1ms取样跨度），最多2次取样，否则TIMEBASE_UNCERTAIN。ledger仍在startRecording之前构造；原mono起点是最后一次初始采样的m1，不从首stamp归零或重置readSamples。
- 当前窗口C与O的可能位移为[C.lower-O.upper,C.upper-O.lower]。只有整个区间位于原[-5,+5]ms才接纳；区间完全在外报告TIMEBASE_CHANGED，交叉而无法证明则最多追加一次新括区间，仍不确定报告TIMEBASE_UNCERTAIN。后一次并非重新设原点，也不能冲销已证明时基变化。固定两次，不睡眠、不读音频、不重连。
- 单次9ms调度产生宽窗口；若第二次窄窗口确证原offset，可通过。真实正负9ms仍失败，真实6ms可能因为量化无法确证变化类别，但仍失败UNCERTAIN。每次+1ms渐变不能更新基线累计放行。宽窗口也可能含suspend，不能仅因区间相交就通过。
- API前后仍只衡量stamp调用；boot取样后最终m1用于checkedAt、stamp年龄、producedUpper、startup500ms/8000samples、native剩余room，追加取样的全部调度耗时不能被扣掉。100ms年龄、15984–16016 rate、2ms runtime phase、3200/320容量/预留、累计读取/首字坐标/取消清零不变。
- sampleTime不能沿用不精确点offset。对mono最早样本时间t，输出floor(t)+O.lower-5ms-原末端1ms舍入。原许可的5ms位移也从样本时间扣除，绝不把新boot观察加到旧样本上。精确同步fixture的O.lower=-1ms，所以相对旧point映射早6ms；这会更早耗尽上传队列age，不会刷新音频。startup原点检查使用相同保守boot下界；mono样本0约束仍在refresh独立检查，read/绝对尾样本坐标不变。
- 这是保持5ms有限模型的保守测量修复；clock read错误、真实大时基变化和持续不确定均failclosed，不能承诺JNI物理可中断或设备不再出现其他故障。

回归oracle差异单列：旧tests假设点offset精确，ledger/bootstrap/Sherpa受控链的sampleTime断言及实际Capture首字时间窗口相应扣除明确6ms，原样本计数/首字坐标/缓存清零断言保留；6ms位移仍拒绝，但由CHANGED改UNCERTAIN。保留变更前日志与原测试源码，不能把oracle更新伪装成全套从未失败。原151row硬件metadata重放及近界正负1100/1250ppm、read672/newupper666即时拒绝、陈旧/回退/重标记/累计loss照常回归，不代表本次306秒实机序列重放（缺原始括区间）。

失败元数据沿原固定标签/256条/15分钟限额，新增origin/current的mono前/boot/mono后、offset上下界、尝试数；无PCM/正文/端点/token/异常message。原bridge_ms保留为点估计辅助字段，判定以显式区间为准。root先独立审新head；如需要新版设备候选，再统一版本/构建/一次有界复验，作者本轮不操作设备。
