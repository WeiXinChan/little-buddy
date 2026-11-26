PR115 / P115-01..04 修复交接

保留独立QA原源码independent-original.py与修前original-failure.log（4FAIL）。QA两项直接调用旧作者fixture作为负输入，因此original-fixture.json冻结修前完整输入；replay只替换该fixture生成函数为读取冻结字节，原四test方法/输入/assertions不改，见test_persistent_tls_qa_replay.py。修后原四项PASS。不得把新增完整正控fixture替换原负输入后宣称原反例通过。

P115-01：_driver/_service入口先核sys.flags.isolated、继承FD、真实父PID/角色/独立会话进程组、源码SHA/本次run绑定。读取该FD的/proc/self/fdinfo实际FLOCK记录（supervisor持有、设备/inode、WRITE全文件锁），然后heavy_lock(同一个fd)核原全局锁inode/root0644，并保留FD至子进程结束。不是enable/环境flag证明，不建新锁。FD从supervisor传给driver，再与IPC FD一起传给service；两端权威摘要相等，父核run/锁inode摘要与自身实际FD一致。不持锁/错误inode/ownerPID/role/source/isolation一律拒绝，入口核验前不启动worker或服务。

P115-02：正常返回的connection_lost_waiter还须非cancelled、无异常；实际websocket State.CLOSED、transport.is_closing=True、连接建立时捕获的原socket句柄fileno=-1共同证明关闭。缺句柄/未知状态/仍开FD不当成功；失败保留peer和当前socket观察句柄，隔离且禁止继续。确认关闭后一起放弃该连接观察引用，不留历史。此反例是受控不一致native状态，不等于已证实际socket泄漏。

P115-03：成功报告顶层字段精确封闭；forced_exit必须显式False、exit严格整数0，禁止failure_kind等未知成功字段。必需最终shutdown见证（全部连接构造、无peer绑定/active/pending/retired/errors），共享额度与shutdown一致并核类型/上限；服务server.wait_closed也必须完成且无异常。强制隔离/缺字段/矛盾终态不可能变cleanup confirmed。已有失败行/artifact不裁剪。旧生产者通常已写失败，此处修父验证，不能宣称旧实测曾把kill当释放。

P115-04：服务见证实际Session对象的weakref identity，导出仅合成session ID+connection的SHA256绑定，原身份不落盘。同连接每轮/stop/恢复必须same_session=True且绑定一致；每个新连接绑定必须不同，并与清理见证匹配。首个已ACK公开材料hash跨轮保留，已播计数逐轮增加，部分ACK stop不增加，恢复增加；旧ACK状态哈希不变仍保留。即使同一个Peer替换为相同语义值/同ID的新Session对象也会拒绝。此处补证据，未断言旧实测发生串会话。

最新21唯一方法PASS/0FAIL/0SKIP（原11+原QA4+新增6），含多组相邻负控：两内部角色同FD正控、无锁/错FD记录/错PID/role/source等拒绝，取消/异常/未完成waiter及活FD/未知原socket拒绝、强制退出/缺shutdown/错误Session绑定/材料丢失等拒绝、真实Session对象替换检测。final-tests.log为最终结果；initial-after.log保留阶段性15项结果。无实际global heavy.lock访问、进程/服务/TLS42/trace/profile/云/设备/部署；FDinfo/进程/锁均替身，actual Session只在内存fixture中构造。真实Linux继承锁与原生关闭可执行性仍待QA/root批准后验证，不能以fixture声称真实42连接通过。A36/P14/full_acceptance仍false，原48MiB归因unknown。
