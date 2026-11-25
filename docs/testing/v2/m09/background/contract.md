# M09 后台清理与生产启动契约

固定main `12aa7a84c23c48e114108fc6fbe9fa7852ce1801`，独立树 `m09-background` / `agent/tita-87-background`。已与b30冻结：本作者仅拥有feedback后台域、相关测试/runner/docs和v2Debug manifest的application android:name；b30独占host/parent/ParentFeedbackRoute及组合APK。不争写主入口Activity/intent、Grant桥或V1 manifest，不混对方未合源码。

## 入口与调度

V2专属FeedbackApplication.onCreate → AndroidFeedbackRuntime.start，初始化单worker与单Engine并立即排队补扫。即使家长页从未打开、没有PIN/Grant/preview也清理本机到期内容。沿用原FeedbackSweepService，未增加服务、广播接收器或前台常驻/WakeLock。

FeedbackMaintenance.start幂等安装60秒进程tick；startup/periodic/OS Job都调用同一request。并发请求合并成一次引擎清理请求（首次构造核心自带初始化sweep），各OS回调分别收到真实布尔结果。注册失败/抛错不阻止清理，下一tick/启动继续重试。tick入队时就把Engine绑定的页面/版本捕获，注册IO不能将旧tick改绑给后来的编辑或新页；沿用R87-03失败隔离。诊断只保留jobScheduled、lastSweepSucceeded有限布尔，不保存材料/异常字符串。

AndroidFeedbackJobSchedule检查同ID、组件、persisted/periodic、15分钟周期和无额外网络/电源/idle限制；匹配就复用，缺失或不匹配才schedule。周期不变，不设置新的截止/阈值；现有RECEIVE_BOOT_COMPLETED权限与persisted job用于重启接续。JobRuns使stop/旧执行不能完成或取消新执行；已经排队的删除继续，但旧JobParameters回调被丢弃。

[Android JobScheduler 官方契约](https://developer.android.com/reference/android/app/job/JobScheduler)说明getPendingJob也包含运行中的任务，同ID重复schedule会停止原执行，因此不能每次JobService启动无条件重排。[JobInfo.Builder 官方契约](https://developer.android.com/reference/android/app/job/JobInfo.Builder)说明持久任务重启载入需boot权限、periodic不保证周期内具体时点。本实现只保证已被唤起时补扫，不能承诺Doze/断电/未解锁/系统强停下精确物理删除。

## 存储所有权及失败

FeedbackCoreOwner在noBackup目录独立owner文件上tryLock；持有至核心/进程寿命终点；这是产品存储锁，不是第二个构建锁，覆盖页面和系统任务共用的全部写入。第二运行时拿不到锁就拒绝，不构造旧快照写者；锁冲突或首次初始化失败释放未成功所有权，后续tick可重试。已发布核心写盘失败继续隔离，不通过自动换核心绕过quarantine。非授权锁，不阻塞ParentDomain撤销；owner文件在vault目录外，不能误触发既有“有材料却缺Keystore key”保护。

源日志按自身7天清理；已选草稿副本由原核心清零ByteArray/范围并使确认失效；问题副本取原单7天与撤回24小时较早截止。离线删除仍保留无正文outbox/原截止和账本，不因本机擦除冒称平台全副本完成。R87-01/02/03、300ms撤销及合法提交/耐久事务协议不改写。

## 外部依赖与证据边界

| 缺口 | 当前端口/默认行为 | 后续所需 |
|---|---|---|
| 真实Provider与全部副本 | FeedbackProvider仍Unavailable；后台不发送、不伪造回执 | 审核端点/归属凭据/回复与全部副本、备份删除证据 |
| 可信时间/设备绑定 | FeedbackClock沿用本地单调连续性与持久高水位检查，非服务时间证明 | 可信服务时间、凭据/设备代际绑定；相关外部承诺默认拒绝 |
| 归属初始化/恢复/D04 | 后台不读PIN/配对、不创建OwnerProof，生产Grant仍由parent负责 | 已核实真实归属及系统认证恢复；不能用安装ID/默认PIN替代 |
| OS/设备 | Application/JobService实际注册和编译，JVM故障/文件验证、APK静态检查 | Android重启/Doze/强停/锁屏、真实Keystore与设备证据仍OPEN |

未新增TLS/网络路径，真实TLS/平台端点执行为0；不为凑用例连外部服务。Linux独立API编译与标准APK验证不证明OS调度已执行、String字节覆写、闪存物理擦除或真实跨设备认证。完整M09/A24–A31、D02/D06及实机/声学继续OPEN。
