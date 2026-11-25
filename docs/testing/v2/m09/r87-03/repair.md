# R87-03 异常 sweep 与旧 UI 投递隔离

继续原PR40、原feedback隔离树与分支，不混M08 parent/host或M06。固定PR base `77893453fa855eb31838ce506fa36b6debe9a696`，修复前head `126d1d36928a6f1e2c25c936814f7218810830b6` / tree `4188a2cf12be8c4ef5d1e40c3e76e52a8c6cc598`。

## 历史失败

QA原报告/原探针/原失败JSON与日志逐字节保存，原断言另纳入Review40RepairProbe.kt，未改弱。QA正常合计80执行、79通过/1失败/0跳过，原79PASS和10突变有效不能覆盖这1项真实失败。作者本轮用 --source-ref 固定上述旧生产源码及 --case Review40RepairProbe#failedExpirySweepMustNotDeliverQueuedExpiredDetail 另复现1执行/1失败/0跳过（编译成功，JUnit exit1），原始记录为old-author-reproduction.json/.log。

根因：真实加密vault写盘失败在成功afterSweep之前抛出，失败分支仅排队错误通知，未清pending/轮换版本，旧详情先投递再显示存储错误。原反例在截止前1ms给新有效页授权、worker产生详情但阻塞UI投递，推进到期限等值后注入实际VaultFiles.replace IOException；false后重开同vault到期为空，放行UI仍先出现含正文Detail。

## 修复

系统tick在入队时（文件IO前）捕获原页面及请求版本。失败只对该目标按CAS轮换版本，同步释放pending、确认token及刷新元数据，取消旧内存草稿，然后投递不含正文的有限错误状态。旧UI票据不再匹配；错误通知自身也核该新版本与当前页授权，撤销则锁页。后来编辑/新页已改变版本或owner时，旧tick不写它的pending、不取消它的草稿、不投递覆盖它的错误通知。页面控件清文本/解绑引用继续沿用R87-02。

FeedbackCore、Vault、授权/Grant端口、parent及M06未改。文件写盘异常不代表耐久删除成功；核心原有隔离继续拒绝，恢复磁盘后同一隔离核心重试仍拒绝，重开真实vault后才重新按截止清理。截止前失败不能假称磁盘中尚合法材料已删除。系统清理/失败失效不需要PIN，无权恢复submit权限；不持授权锁跨IO。

## 新增验证范围

原QA探针不变，另加12项实际引擎/真实文件AES-GCM反例：排队列表与回复、已显示详情、截止前失败与磁盘材料仍合法、失败重试与健康重启清理、无家长页、授权撤销、错误排队后编辑、写盘失败期间新编辑、写盘失败期间新页面、close后错误不可恢复旧页、tick排队后worker启动前编辑或新页。使用合成时钟/授权/Provider，故障在真实VaultFiles端口注入；不以provider spy代耐久路径。

负控新增恢复原失败分支（只排队Notice、保留旧pending/version），运行同一QA原断言；须编译成功并命中“先暴露正文”原断言，不能以初始化/编译失败冒充。另一个新负控将目标捕获延后到worker开始时，必须命中tick排队后新编辑被误取消的反例；原10负控继续回归。

## 资源与未测边界

原作者与QA的Gradle缺SDK失败原件保持原样（../ui/gradle.log与../r87-02/old-qa-gradle.log），资源未变，不重复相同失败命令。Android API编译不是APK/控件屏幕或String覆写证明，未做真机Keystore/OS调度验证。工厂/真实Grant/主入口仍未装配；完整M09/A24–A31/D02D06、Provider全副本删除、归属恢复/可信时钟设备绑定/OS调度/物理音频与真机验收分别OPEN。heavy.lock全局1；无Mac/手机/模拟器mic/HDA派工，无部署或自行合并，无用户过程操作。

## 最终正常结果与复现

92执行、92通过、0失败、0跳过，编译成功、JUnit exit0；原79项 + 原QA异常探针1 + 新失败流程12项。最终生产/测试源哈希逐项匹配baseline.json。核心/Vault/授权端口/工厂与原126d1d3字节一致。源码空白检查通过，原始日志尾空白按原件保存。

```sh
scripts/with-build-lock python3 scripts/test-m09-core.py --source-ref 126d1d36928a6f1e2c25c936814f7218810830b6 --case Review40RepairProbe#failedExpirySweepMustNotDeliverQueuedExpiredDetail --out build/m09-core/r87-03-old.json
scripts/with-build-lock python3 scripts/test-m09-core.py --android-jar "$ANDROID_API_JAR" --out build/m09-core/r87-03-final-baseline.json
scripts/with-build-lock python3 scripts/test-m09-core.py --negative-controls --out build/m09-core/r87-03-final-negative.json
```

API jar SHA256 `7123df2cceaebc66f3991a480964968c9d9603f6abd542ea8878c39db70fcb07`；包含真实feedback/parent及Android页面/工厂/JobService编译，无APK或屏幕实测。中间90项通过后增加排队边界反例并调整目标捕获时点；旧源中间负控由本作者停止（wrapper exit143），不计入最终通过/检测分母，最终12突变重新从头编译运行。

## 最终负控结果

12个突变全部独立编译成功，各执行1项、预期断言失败1项、跳过0，12/12检测有效。新增failed-sweep-cache实际命中原“R87-03: failed expiry sweep allows queued expired detail to render before the error notice”断言；late-failure-target命中排队后合法编辑应保留的断言。完整trace与最终源SHA-256见negative.log/json。主命令exit0表示所有检测有效，不是把子断言失败计为正常通过。

| 分母 | 执行 | 通过/检测有效 | 失败 | 跳过 |
|---|---:|---:|---:|---:|
| 修复前QA正常合计（历史原件） | 80 | 79 | 1 | 0 |
| 本轮固定旧head原断言另复现 | 1 | 0 | 1（旧缺陷） | 0 |
| 最终新源正常回归/API编译 | 92 | 92 | 0 | 0 |
| 最终新源独立突变负控 | 12 | 12检测有效 | 12预期断言失败 | 0 |

R87-01/02、成功tick、300ms阻塞IO撤销、耐久outbox/合法提交/旧任务隔离与默认拒绝均包含于正常回归并通过。修复仅供原QA定向独立复核、root审合，未自行合并。
