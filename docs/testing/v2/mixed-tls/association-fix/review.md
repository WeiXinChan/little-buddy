PR116 M116-01..04 五个负控收敛

已读QA最终report.json/calibrated-replay.log（4733add0上合格旧schema基线仍5FAIL；shutdown已关闭），引用hash见qa-reference.json。原QA源码原样保留independent-original.py、当时基线original-fixture.json和本地修前original-failure.log（6方法1PASS/5FAIL）。test_mixed_tls_qa_original只注入冻结旧fixture，原六方法/变异/断言不改。

旧输入拒绝不能证明全部关闭：新字段是为真实观察增加，旧正控本身也不再完整。因此另构造完整新正控（含真实生产者同名观察字段、活动/清理事件、部分输入和全部shutdown字段），每个新增负控先验证它通过，再只变相应关联/状态/媒体/截止/事件。原采样方法自带“输入没有活动事件”的assertFalse，保持在冻结旧输入上复跑；新正控另仅删除其指定四类事件并沿用同样拒绝断言。positive-receipt.json明确metadata_fixture_only_not_native，不冒充90秒实跑。

M116-01 关联与状态：turn必须归属connection_index、实际binding及同Session见证；顺序step/fault/status必须符合固定块（7正常、stop、恢复、末fault）。connection状态必须等于末turn实际结果；ASR/PLAN RST末轮0ACK只能fault_injected，不能因前面已有交付而标delivered。完整交付的head、game、首个已播材料/计数/hash与真实turn_delivered快照一致，连接帧/ACK总账等于各turn实际观察量；未播/截止不造听过事实。

M116-02 实际媒体：逐包成功send后记sent，20ms节拍完成才记paced；最后input seq通过真实VoicePeer barrier后读取capture_bytes，完整输入必须实际缓冲96000样本，不把期望写回。当前epoch PCM解码、段唯一、样本头连续检查后记录received（包含故障策略不ACK的包）；ACK实际send完成后才记acked/head及播放秒数，另保留发送尝试计数以区分取消时不确定send。完整固定回复48000样本/20包，部分故障与cutoff分开；逐turn/global的sent/输入/播放、帧/ACK与墙时核对。补了计数/ACK/墙时都同步缩小的反例，不能仅因别名不等或墙时总和错误才拒绝。

M116-03 实际事件：生产者快照增加active、capture、pending_audio、head、同Session/已播/玩法/hash等当前状态。父按connection/turn索引核input开始/结束、真实活跃首音频、交付或stop、清理前后；完整输入finish须capture192000字节，首音频时generation活跃且有待ACK段，交付/stop须满足ACK及状态证据。跨事件/窗口顺序、播放字节所需时间、清理后零在途/材料都核验，不只是标签集合。周期采样仍不是连续峰值。默认持久TLS工具只加一个空on_audio钩子供新模式观察已收到但未ACK包，原行为不改。

M116-04 截止：单调钟固定timeout_at(driver.started+duration)，仅真实window.expired()可产生outer_work_window见证。取消第一时间记录turn/connection.cancelled_at，不能靠稍后最终采样90秒掩盖80秒结束；cutoff点须在原deadline至+1秒调度观察窗，完成/终态至多+15秒有限清理。此为证据有效性检查，不延长产品响应预算/TTL。输入未完/回复未完整播放按实际计数保留；未admitted/无法证实关闭仍失败unknown，不造peer/构造数。清理前先停止并有限观察驱动接收/ACK任务，冻结实际计数后收集清理证据，防退出窗口继续ACK。

49之前的阶段结果不作为额外分母。最新51唯一方法PASS/0FAIL/0SKIP（旧混合7+shutdown5+新关联/观察12+原QA6+受影响旧持久工具21），tests.log。包括完整正控、五类对应变异、保持计数/墙时一致的缩小工作量、错索引/活动值/截止owner、真实buffer返回320不补96000、重复PCM不重复计数等；所有都是小对象/fakeclock/JSON/替身，不运行原生服务、真实锁、90/3600秒、worker、云/设备/部署，不跑旧全后端。

当前只交QA准备审查。完整A36/P14、真实供应商/设备/声学/账单仍OPEN；源码可执行性与实际长时趋势尚未验证，acceptance恒false。旧实跑报告、PR115冻结head及已关闭shutdown证据不改。
