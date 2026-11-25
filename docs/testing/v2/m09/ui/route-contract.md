# M09 页面/管理 host 接线契约 v1

固定 base `77893453fa855eb31838ce506fa36b6debe9a696`。M09 拥有 feedback 包、反馈 JobService 和对应 manifest service/boot permission；M08 拥有 parent 包与管理 host/入口。双方不争写 host 文件。

M09 提供 Kotlin internal API：

```kotlin
fun interface FeedbackGrantGate {
    fun accept(domain: ParentDomain, grant: ParentDomain.Grant, decision: () -> Unit): Boolean
}
object FeedbackPageFactory {
    fun create(activity: Activity, domain: ParentDomain, grant: ParentDomain.Grant,
               gate: FeedbackGrantGate, onExit: () -> Unit): FeedbackPageHandle
}
interface FeedbackPageHandle {
    val view: View
    fun pause() // HOME / onPause / focus loss: instant epoch invalidation, scrub display, async draft cancellation
    fun close() // onDestroy / route exit; idempotent, no blocking IO
}
```

host 只给经真实 PIN 校验得到的进程内 Grant，不从 extras/保存状态重建；反馈内部不初始化 PIN，不变更配对。host 切入后挂载 view；HOME/onPause/失焦/退出先 domain.revoke，再 handle.pause/close；正常内部路由先 nextPage 轮换 Grant，再 close 旧 handle，host 决定返回位置。页面失效后不能 resume 旧 handle，须重新校验并创建新 handle。反馈按钮只能使用本 session capability。

基线 ParentDomain 还没有 final decision 扩展。M08 需在自己分支提供：

```kotlin
fun acceptProtected(candidate: Grant, decision: () -> Unit): Boolean
fun isAuthorized(candidate: Grant): Boolean // 仅早验
fun nextPage(candidate: Grant): Grant? // 原子轮页，保留原 deadline
fun revokePage(candidate: Grant) // 仅撤旧页，不误伤更晚页
```

内部复用真实 valid(candidate)/generation/pageEpoch、ParentEpoch.claim 及单调时钟 post-CAS 截止见证；在最终授权点同步执行短 decision（仅内存发布），不持授权锁跨文件/网络/KDF IO，不缓存早期 Boolean。已决定事务按真实持久结果完成，HOME revoke 不能等待 worker。M09 gate 的 host 适配仅将给定 domain/grant 委托到该方法；没有适配时必须用拒绝 gate，不用 volumeLimit/localAction 早期检查冒充 commit。

本 PR 用同一真实 ParentDomain/Grant 的适配器和 gate 契约编译，host 与新增 parent 方法合入后的实际装配由 M08/后续依赖 PR 接入；不复制未合 parent 源码。缺可信 OwnerProof 时没有可用 Grant，生产自然保持拒绝。UI 的纯说明/日志预览、列表详情、整单撤回、清本地源日志各自重验；无 Provider 显示明确不可用，不发送或宣称远端已删除。

本地运行时进程单例、单 worker 串行写同一 Keystore vault，页面离开不关闭系统清理。进程内定时 sweep + JobScheduler 持久 periodic job 接续进程重启（系统可能延迟任务，不能保证断电/Doze 下物理擦除准点）；访问时亦受不可续期截止约束。实际平台全部副本删除、真实设备绑定/可信服务时间仍 OPEN。

M08 已接受 v1 签名。旧 handle 不 resume；feedback 的 pause/close 只撤销本页本地 epoch 并擦除 UI/草稿，不调用无条件 domain.revoke，也不延长新页 idle 截止。基线的 volumeLimit 只用作保守早验，最终门禁只能由 host 委托 acceptProtected。
