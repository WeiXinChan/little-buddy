# M09 本地页面与清理集成

固定 base：`77893453fa855eb31838ce506fa36b6debe9a696`。独立分支 `agent/tita-87-feedback-ui`；不改 parent、管理 host 或 M06 树。

## 实现与边界

原生页面工厂提供本机列表/详情、家长说明、默认不选日志的精确时间范围预览/确认、提交/回复状态、整单撤回、本机问题副本清除和独立源日志清除。文本不写 saved state/autofill，窗口 FLAG_SECURE；离页立即清文本、撤销本页 epoch，迟到 worker/UI 回调不能恢复旧内容。回复只展示本机已收到材料，不轮询虚构服务。

FeedbackEngine 是进程单实例的单 worker；真实 AndroidFeedbackVault/Keystore 只在 worker 打开。父域门禁通过独立 FeedbackGrantGate 端口，缺失默认拒绝。准备、文件暂存（可丢弃密文）、短内存不可逆决定、最终持久化结果及 provider admit 各有独立边界：不得把 accept 返回 Boolean 作为后续 IO 通行证；保留原核心阻塞 IO 撤销负控与提交失败/撤回状态。合法提交点已过按事务结果完成，页面退出不伪造取消。

新 CLEAR_LOCAL 复用 protectedChange 最终授权/耐久提交协议，仅擦本机这单正文、日志和回复；保留幂等编号、远端状态、原始截止及删除任务，迟到回复不能复活副本。不清源日志、PIN、配对，也不声称平台删除。schema1 读取后迁移 schema2，增加 localCleared；没有延长保留期限。

系统清理无需 PIN 或新 preview：进程存活每60秒 sweep，另以 BIND_JOB_SERVICE 保护的 persisted JobScheduler 15分钟任务接续进程重启；失效父页在 tick 后锁页并取消草稿。服务仅有删除权限，不产生 submit 授权。保留多草稿、部分过期、恰好截止、重复清理及确认失效原断言。

## 已知限制与 OPEN

M08 host/parent 独立分支接受 route-contract v1；本轮不复制其未合代码，真实 acceptProtected 门禁和页面路由最终装配属于后续依赖 PR。因此当前主入口还不能打开此页面。真实归属初始化/系统认证恢复仍是 Grant 来源缺口，不能注入测试 OwnerProof 到生产。

Provider 当前默认不可用，页面明确显示、禁发送、不自动排队。平台端点、归属凭据、设备绑定、回复获取、真实全部副本/备份删除回执均 OPEN。本机不同 vault 的隔离测试不能替代真实跨设备凭据验证。

AndroidFeedbackClock 只给进程内本地单调连续性，非可信服务时间；重启/改时/断电与 OS Doze 调度不能保证准点物理删除。JobScheduler 已实现并编译，但系统重启/Keystore/页面渲染未在设备执行。未新派 Mac、手机、模拟器或麦克风/HDA 试验，不能把这些恢复作为本轮前置。完整 M09/A24–A31、D02/D06 和产品验收继续 OPEN。
