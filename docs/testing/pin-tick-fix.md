RC8 owner PIN tick 竞态的独立修复候选

基于精确 cf187d4。与诊断分支/首复现 APK 分离，不构建或安装此分支业务包。

可重复反例：fresh owner receipt 在 replacePin 前置检查后被消费，challenge=null；
worker 阻塞在 hash 或 commit，真实 UI tick 因 challenge 不再 current 而 revoke page。
最终事务拒绝，record 仍 null，UI 回 UNOWNED。原 RC8 的四条期望断言两失败，
expiry/cancel 两拒绝通过；不证明 OPPO 真实故障根因。

修复区分 receipt 可消费性与已消费操作的生命周期见证。savingChallenge 只在
replacePin 已通过原前置条件后设置，仅保存对象身份，不签发 Grant/receipt。
worker finally 清除。仅 busy OWNER_PIN 的 tick 使用 ownerSaveCurrent；它仍核
相同 page epoch、对象身份、未隔离和原 expiresAt，过期/撤销/失焦均不可忽略。
未开始的排队保存仍用原 challenge 身份；其他页面沿原检查。

最终事务/receipt consume/期限/CAS/存储隔离未修改，生命周期检查不是跨 IO 授权。
不简单跳过 busy 的 tick，不延长任何期限。worker 完成后、UI 回调前若 tick
已观察 epoch 失效，仍锁页；已提交记录保留，不能借此复活授权。

    scripts/with-build-lock python3 scripts/pin-tick-fix-tests.py

复用未改动的四条断言：hash/tick 与 staging/tick 应保存，真实 expiry 和
pause/cancel 仍拒绝。作者不做设备/云/后端/版本改动；由 root 审核决定接续。
