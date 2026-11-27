# 冷档检索 query 在审核中的一致性

基线8682（产品等价fe49）。root原失败 `finite-cold-query-8682f5a-once/result.json` 保留不改：3请求、PLAN正确、whole allow=true/quality=false、0ACK、cleanup确认。本作者无法直接读root0700原件，未绕权限；实际结果数值来自root证据交接。未存供应商自由理由，不能断言上下文缺失是quality拒绝的唯一原因。

源码可证：PLAN用当前原始输入query，whole/segment review原先调用空query；cold检索相关排序不同。离线确定性反例以源确实在archive且不在facts/recent/heard建立，模型审核只在权威context含精确source_id/原文时给quality=true。修前实际VoicePeer 0audio/voice失败，修后PLAN/whole/两segment均见同来源且最终ACK。此为上下文因果，不是对真实供应商拒绝理由的反推。

最小生产变化仅voice.py：review接受query；whole和segment调用均传该respond闭包中的原始text。每次先operation.ensure，然后重新调用operation.session.context(query=...)，并经owned检查调用前后所有权。未保存PLAN快照、不把待审句当query、不填事实、不降低安全/quality审核。FACTS已经提交的新来源可见、已ACK内容随Session更新；private/shared过滤由当前Session投影控制，旧private快照不被带回。换人/取消/epoch/revision/Session/TTL边界不变；共享retry/预算/释放.5秒未改。

新增6方法涵盖实际cold PLAN→whole/segment→ACK、新facts提交后fresh projection、未命中继续quality拒绝且无audio/state、stale epoch/revision/session/cancel/expiry不得投影、shared不复制private、晚到review在取消后不得发布。另复用已有private→shared压缩/旧参与者晚到/原safety负控。

维护变更：20个历史工具方法中的pin身份检查改为读取声明source的不可变Git对象核对整个manifest，不要求未来worktree永远匹配旧版本。执行端verify_source完全未改，仍逐字比当前文件；新增临时copy负控证明正确原字节可准入、改字节必须source_bytes拒绝。未更新旧source或将旧失败冒充新结果。

针对性共30项PASS（原20工具+1本地字节拒绝+6修复方法+3现有边界），不重复全集。新cold复验工具另固定pin提交；前三个真实通过case不重跑。本作者0云/长测/部署/设备，完整A12语义仍待root唯一cold实测。
