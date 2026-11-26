PR111 MEM111-01/02追加修复，仅轻量fixture。固定旧head26eb3e4；未更改生产/其他PR，未执行真实worker/profile/run_soak/tracemalloc负载、未打开或争抢heavy.lock，未触session75560。3aa归因仍unknown。

原件：QA pr111-review/review.md/independent.py已读取。原independent.py逐字复制为tests/v2/test_soak_memory_independent.py，sha256 `4297c3d375d4b1357d5ad1e22561e214d867a9be43068df760abd1fb66461dd2`。原输入、assertions不改；original-failure.log记录本地修前3方法1PASS/2FAIL。修后independent-after.log及final.log保留原断言通过：MALFORMED_CHILD_TERMINAL=worker_failed_stopped、DIFFERENT_SAMPLE_COUNTS=false；busy锁负控完全使用替身fd/metadata/flock。

MEM111-01：

- schema升级format2；父为每个臂产生一次性worker_id，与固定source/arm/attempt_limit绑定。子worker回传该身份，不能将另一臂/旧结果/错误SHA当当前结果。它只是本地监督关联标签，不是安全远程执行证明。
- 必需字段和类型在completed接纳之前全部检查：cleanup不缺省成功，attempt/失败计数、hash、报告保留结构、四阶段/弱对象/上下文计数、trace元数据与分组、测量开销均受约束；bool不冒充int，NaN期限拒绝，未知字段不进结果。校验用实际条件而非可被-O移除的assert。
- 父另外读取该臂已保存的完整报告，核普通单链文件/尺寸/SHA、实际attempt/sample/observations/evicted、cleanup/模型计数及输入输出排程hash；不能只相信返回的hash或采样数量。完整report保持原样，不剪样本。
- JSON解析、身份/字段/完整报告校验、workload/cleanup判断均在同一监督try内。缺字段/坏身份/坏报告统一worker_failed_stopped+固定failure+attribution unknown；有效但失败的workload/cleanup另写workload_or_cleanup_failed_stopped。比较阶段异常写comparison_failed_stopped。坏元数据不写入completed，之前验证过的臂和各臂artifact不删除，不启动后续臂，无自动重试；不暴露原异常或候选正文。

MEM111-02：

- workload_schedule_comparable仅表示前三臂实际attempt/输入输出排程/model计数相同，不代表内存条件相同。
- memory_controls单列每臂完整报告sample/attempt保留数、总observations/evicted、文件字节和顶层字段数；四阶段report_reachable_bytes及trace自身元数据；phase/checkpoint行数、弱引用观察/槽数、trace帧数。所有这些量也可能贡献分配，不能将差直接归为tracer或生产。
- comparable保留为保守的memory_controls别名，要求报告保留结构、测量工作和报告图估算等观测条件一致，并满足原workload条件；不再是仅工作量比较。100/200/200的原QA表达式及完整父监督fixture都返回memory false，同时workload_schedule仍可为true。
- plain与traced本来就有不同的trace配置，memory measurement_conditions_equal通常为false；这是探索设计中的已知差，不是让工具反复重跑直到“刷成true”。即使保守比较为true，也不是生产对象身份或泄漏因果证明。结果继续controls_collected_not_leak_verdict/requires_review，idle仍不是相同工作负载。

验证：19唯一方法19PASS/0FAIL/0SKIP（旧准备9、QA原3、新父监督fixture7），final.log。新7方法中含每个必需字段逐一删除、身份/类型/阶段/结构拒绝、完整报告缺失/hash/行数不实、第二臂失败保留第一臂字节和已验证结果、比较异常终态、完整100/200/200与相同样本但不同trace条件正反检查。旧作者cleanup失败fixture改为完整format2但cleanup=false，原终态断言保留；QA三方法输入/断言完全未改。数量多的表驱动子例不另算方法/独立突变。

命令：python3 -m unittest tests.v2.test_soak_memory_diagnostic tests.v2.test_soak_memory_worker_validation tests.v2.test_soak_memory_independent -v

仅调用父监督函数的替身fixture：archive为空临时tar、process返回合成JSON并写临时小报告、lock上下文/fd完全替身；无真实子进程/锁/生产导入/trace采集。原3aa120attempt/1325样本和RSS报告未修改，也没有新增内存归因测量或生产泄漏结论。N6仍需原QA关闭HOLD且root确认锁释放后另行安排，不自动执行。
