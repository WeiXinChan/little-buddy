# M08/M09 页面契约 v1

基线 main `77893453fa855eb31838ce506fa36b6debe9a696`。
本任务隔离目录 `tita-86-8c4eebd1bbc1/workdir/little-buddy`，分支 `agent/tita-86-parent-ui`。
M08拥有parent、管理host及路由装配；M09拥有feedback页面/域及JobService。双方不争写。

采用M09提供的Kotlin internal契约，不在M08复制尚未合入的feedback页面：

```kotlin
fun interface FeedbackGrantGate {
    fun accept(domain: ParentDomain, grant: ParentDomain.Grant, decision: () -> Unit): Boolean
}
// FeedbackPageFactory.create(activity, domain, grant, gate, onExit): FeedbackPageHandle
// handle: val view: View; fun pause(); fun close()
```

M08冻结并实现ParentDomain接口：

```kotlin
fun acceptProtected(candidate: Grant, decision: () -> Unit): Boolean
fun isAuthorized(candidate: Grant): Boolean
fun nextPage(candidate: Grant): Grant?
fun revokePage(candidate: Grant)
```

acceptProtected在worker最终点重验真实Grant引用、generation、pageEpoch和闲置期限，
沿用CAS后期限见证；只执行一次同步短内存decision，不持状态锁跨IO。Boolean只是该次
具体决定的结果，不能缓存后用于未来IO许可；prepare/早验不能代替accept。失效返回false。
反馈gate仅委托给给定domain.acceptProtected(grant, decision)，无本地accepted缓存。

内部设置/反馈导航由host先nextPage轮换真实Grant，保留原闲置期限，不重复PIN；旧页Grant
和异步回调立即失效。忙/过期/竞争失败时锁定。退出/后台/失焦/销毁先原子撤销本host页再
pause/close并清输入。旧handle不resume，重新进入创建新handle。
host使用invalidatePage(pageEpoch)定向失效，重复销毁旧host不会误伤后来host的页面。
pause/close只清页面与回调；若需撤销权限，只可revokePage(该handle的旧Grant)，不能无条件
revoke整个共享domain而误伤已经轮换后的新页。route onExit仅是导航请求，不自动续期。

M08本轮不依赖M09尚未合入的类完成编译；父域提供独立页面适配端口，默认反馈路由未装配。
两支合入后用小型依赖PR将上述工厂接到host；不能以占位路由宣称反馈页面已接通。
真实归属/设备绑定及系统恢复未配置默认拒绝；无Intent extra/测试OwnerProof生产赋权。
VoiceClient/M06音频管理暂停契约未合，真实语音事件/采样门控仍OPEN，不复制PR36。
