TLS内存归因的最小准备，实际14连接尚未执行。独立分支从冻结c4864f78868ab29f50713ca214f82554801c6248起步，仅新增诊断脚本/fixture/文档，不改原TLS/duplex/VoicePeer/provider/RC9/生产/签名。旧duplex PR111不作为本批TLS增长解释。

已读QA tls-retention-source-audit/review.md和tls3600-final-review/review.json，并只读复算原tls-soak-3600-c4864f78.json。read-only.json与QA原SHA c2715a2608791d48ece4f8b579dfabfc69c8e656b5d0d88fb4ff9b98bf27648c一致；117连接、2119样本，RSS35209216→85975040（+50765824 bytes /48.4140625MiB），归因unknown。该source关联来自QA与原报告hash，不是报告自行提供的执行证明。原文件不改、不重跑、不裁采样或分母。

可证工具引用：c486的transport.peers/relays/connections/tasks一直保留历史；raw connection row还有peer/relay/client tasks/Events/ACK元数据；relay.links保留StreamWriter对，relay.tasks和peer.retained保留done Tasks；collector→transport→peer→observer.record存在强环。源close确认I/O/Task结束，未清这些历史集合。pending0不是对象析构，也不能把48.414MiB逐字节分给这些结构。全进程包含合成client/server/relay/Python/OpenSSL，非单独部署backend RSS。

新增scripts/v2_tls_retention.py（默认禁用）：

- analyze仅读原TLS报告，保留117总账并输出快照差。实际short14必须--enable；父非阻塞获取原root:root644 heavy.lock，不创建第二锁、不等待/偷换。固定git archive c486源码到临时目录，隔离子进程(-I/原锁FD/nonce)，仅原合成provider。原产品、ASR/PLAN/部分ACK、RST/暂停/半开/stop、新Session与恢复时序全部由原run_tls_soak执行，没有复制或改VoicePeer。
- 每次命令只运行一臂、固定14连接/seed17：一个七类故障及恢复循环。原Limits duration12/interval.05/sample.05/attempt2/max14，产品预算/TTL/.5释放不改；父child45秒/源码export10秒上限，失败停止、artifact保留，不自动重试。不是一口气42连接；另两臂必须root另行选择、各自单独输出。
- retain_plain为首个默认候选；retain_traced仅增加tracemalloc8帧；release_plain与retain_plain相同工作负载，唯一控制在14连接及全局close完成、完整原报告保存后，释放已确认关闭的测试工具历史引用。parent核source/arm/nonce/报告SHA与字节/14分母/完整故障顺序/清理/采集计数和原计数绑定。结果只controls_collected_not_attribution，不自动宣布可比/无泄漏。
- 每连接记录closed_before_attempt_task_return：这是Task即将返回而非Task已析构，不把当时1个当前Task计作泄漏。记录peer/relay/raw row/global/peer-retained/relay-task引用槽及去重done/pending句柄、writer槽/去重数，弱观察peer/Session/WebSocket/TCP/SSL wrapper/Task。槽数不是全局强refcount；不支持弱引用时显式unsupported_observations（观察次数，不是去重对象数）。不输出对象repr/地址/正文/PCM/包/证书/nonce之外身份。
- 六阶段：导入GC基线；report held+owner held；原报告保存后loop-turn+GC；history retained或confirmed history control；释放本地report引用后loop-turn+GC且owner仍持有；释放observer对owner引用后loop-turn+GC。完整原report先以独立artifact保存/SHA，不删除报告、不清原source分母。lifetime_connections保持14，history引用槽可在控制后为0，两者分开。
- 控制释放及最后丢owner前均严格确认closed/非quarantine/allowance关闭、所有已知任务done且无异常、server停止/handler空、peer run结束/Session清空、WebSocket connection_lost完成且底层FD关闭、relay停/Writer is_closing及protocol._closed完成/FD关闭。未知、未确认或失败一律拒绝，不作历史集合的部分清除。检查全部通过后只清诊断owner历史列表/Task集合/relay links及relay历史Task，绝不改生产Peer/Session/provider字段；不再调用close/reset或继续连接。实际私有API兼容性仍需QA/root首个真实短跑验证，缺失即拒绝而非假定关闭。

relay计数语义：

原报告attempt.relay_network_errors合77，最终ledger合311，每连接+2共234。源码global close再次对旧writer对调用reset，setsockopt失败也计入network_errors；这与数字一致，但没有历史syscall跟踪，不能断言234是新网络故障或完全证明其来源。read-only分析标historical_syscall_cause=unproven，不改原字段。

观察子类完整委托原reset/pipe_bytes/close：新增reset_calls、同步reset前后legacy增量(reset_setup_errors)、pipe_bytes真实抛出且重抛的I/O异常计数、剩余unclassified_legacy；按workload/connection_cleanup/post_connection_cleanup/global_cleanup/post_global_cleanup分阶段。reset无await，前后增量直接来自原SO_LINGER异常计数路径；close阶段由原owner.closed状态标记。未覆盖的open/setup等残差只标未分类，不强说I/O故障。不跳过原重复reset、不清legacy值、不重写原报告或为洗77/311重跑一小时。

8项准备fixture（preparation-tests.log，8PASS/0FAIL/0SKIP，约0.03秒）：小型已关闭对象图释放/weak不保活且保存的14分母不变；任一pending/异常/quarantine/连接lost未完成/活FD原子拒绝且集合不变；假closed-writer重复reset两项setup增量与pipe I/O分开、legacy仍原值；只读快照差分析；默认/未知arm不触锁/worker；父不完整JSON终态并保留artifact不重试；假snapshot分配组和unsupported weak标记；三个选择臂各自一次14-row假artifact的父契约。全部锁/archive/process/socket/future/snapshot皆替身，无实际TLS/worker/profile/run_soak/tracemalloc负载或heavy.lock访问。不是原8项真实网络回归，也不是新实际短跑通过。

内存判读边界：

- Python trace按分配点分组(diagnostic/TLS工具/采样工具/production/asyncio/ssl.py/other)，不是引用拥有者；ssl.py组只代表Python wrapper，不含全部OpenSSL/SSLContext/libc分配，kernel socket缓冲也不等于进程RSS。tracer自身表及snapshot/弱观察/边界计数有成本，返回tracer_metadata与point/boundary/样本数量/报告文件字节等。native_tls_allocations_measured恒false。
- 保存报告本身、诊断history、closed对象强环与Python/libc arena都可能影响RSS；释放后RSS不降不证明仍有live对象，weak归零也不证明所有native字节都归还。单次curve不宣称平台。只要未确认就保留并停，不允许清产品对象刷平。
- 不同arm会生成新临时证书/连接、时序与采样量可能不同；先核原14工作量、实际sample/observations与测量开销，再人工判是否能比较，不能把plain/traced差直接归为生产或TLS native。保留真实完整报告与六阶段数据，不通过删报告/改分母让曲线好看。

root独立审查后可另行安排首个保留臂（本轮不执行）：

```sh
python3 -m scripts.v2_tls_retention short14 --enable --arm retain_plain --output ./tls14-retain-plain
```

工具自己拿原heavy.lock，不嵌套with-build-lock。先审核这一臂实际14/nonce/source、完整artifact与阶段/关闭确认，再决定是否另行批准retain_traced或release_plain；没有自动后续臂或重试。需使用预期依赖可用的固定解释器、从本PR固定不可变源码运行；root的RC9/生产/签名不变。本批未执行新长测/真实profile、无云/设备/部署/新agent。A36/P14/内存稳定性仍OPEN，旧117连接生命周期正证据与其恢复尾部缺口保持原结论。

PR114增量修复见tls14-fix/review.md：原四FAIL保留，父验证实际交付/故障/ledger/采样覆盖及白名单失败诊断；最新18轻量方法通过，替代此前8项准备检查的分母。未执行TLS14；14连接为七种模式及恢复的一轮。
