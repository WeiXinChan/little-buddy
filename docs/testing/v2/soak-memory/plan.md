本批仅轻量准备。未运行tracemalloc、VoicePeer对照、profile或新长测，未打开/争抢heavy.lock，未观察/控制session75560/PID3943853，不改PR108分支或在途源码。PR108 root修复f5b38d4及QA23PASS仅作为背景，不重复改动。没有已证生产泄漏。

只读复算：已读root offline-soak-3600-3aa8902f.json及QA soak3600-evidence-review/review.md。原报告sha256 `00fd5e03b97726825aee7c713b62e8868b11545f2298a3a04a9aebc330f8d03e`；120 attempt（80交付/40预设stop）、1325样本，六段数量221/220/220/220/220/224。RSS37289984→38424576，增加1134592 bytes；六段仍升、未平台。FD/线程恒定与pending0不证明无泄漏。只读分析JSON保留各段首末值和分母，未修改原件。

源码定位（固定3aa8902f93db2e2a83577a50f32edccf8d42cd50）：

- scripts/v2_soak.py:235–243，ResourceCollector.rows是maxlen4096的deque；本次1325无淘汰。351将同一批row dict放进报告list，不能说1325字典复制了两遍，但临时存在deque/list两组引用。
- scripts/v2_soak.py:278、301–304，attempts追加120行；每行新建attempt Task和stopper Task。scripts/v2_multiturn_probe.py:24–34的BatchState.tasks只add，不移除done。sampler另1，因此源码推导约241个owner句柄，而不是从原进程heap测出的241。
- 最后RSS采样在scripts/v2_soak.py:350，仍在run_soak frame内；ownership.tasks、collector.rows、attempts、transport等局部引用尚存在。这是确定的报告阶段持有关系，不等于确定生产泄漏或1134592 bytes精确归因。
- scripts/v2_soak.py:279–281的ObservedScopes/ObservedRetired.capture是collector.record绑定方法；collector.transport→BackendTransport.peer→generation_scopes/retired_tasks→capture→collector构成可回收环。该环生命周期及取消异常Task是否另有保留引用，原报告无法证明；仅pending计数不够。
- backend/v2/voice.py:231–235 track_retired有done回收；1126在respond finally pop generation_scopes。Session.clear（session.py:123–137）清public/private/recent/facts/source_archive/game/secrets等。代码有清理路径不等于已证明对象都析构。
- Session同会话上下文、公有已播事实、有限recent、来源archive及Python分配器保留页可能分别贡献。需计数/weakref/heap对照，不能以RSS单一趋势判断。

可审工具scripts/v2_soak_memory.py：

1. `analyze`只读现有明确offline/非设备的队列报告，按6×600秒复算；拒绝未知cloud/device层。给出的decoded_report_reachable_bytes=881563是本进程JSON解码图的sys.getsizeof估算，共享identity计一次，绝不是原1325样本的历史heap/RSS所有权，更不能拿它直接减RSS判定“已解释多少”。
2. 准备中的profile父监督串行导出固定SHA到临时目录，独立Python子进程运行plain、traced、traced_repeat、idle四臂。前3臂相同固定attempt数6/12/24、同一冻结SCENARIOS/输入，无expected注入、无产品修改。校验分母、输入排程hash、实际状态/帧/玩法输出排程hash及model阶段计数一致，否则不可比较。idle仅相同导入/墙钟的测量底噪，不是相同工作负载，不计作有效attempt。
3. plain和traced共用相同weakref观察子类和完整输出路径，生产Session/VoicePeer不覆写行为；traced额外开启8帧tracemalloc，输出runner、voice、session、memory、asyncio、measurement、serialization、other分组的bytes/blocks及trace自身元数据。分组按分配点，不是对象所有者或引用链结论；不输出栈原文、源码、文件路径、locals、正文或对象repr。
4. 每臂四点：导入/GC基线；原run_soak返回时报告仍持有；完整报告落盘且GC后继续持有；诊断子进程内删除本地报告引用再GC。后两点均先让出一个事件循环轮次供done回调收尾，避免把尚未执行的回调直接判为保活泄漏。释放只是归因操作，完整report/attempt/sample先原样写入`<arm>-full-soak.json`并hash，永不删样本、清任务集合或重置分母。每attempt另记真实Session字段长度、owner done/pending句柄、样本数及weak生产对象/Task/Operation存活计数，不读字段值。后两点RSS不回落可能只是Python arena，不能据此判泄漏；weakref清零也不证明所有未观察native对象无残留。
5. profile默认禁用；必须显式--execute-profile，父进程非阻塞取得同一个现有root:root644 heavy.lock，忙则拒绝不等待/偷换。子进程必须-I隔离、显式执行标志及继承的同inode锁FD，不能直接走隐藏_worker绕过。仅默认合成provider，没有云/设备/未知数据入口。四臂串行、每臂默认30秒/上限120秒父监督，失败/未确认清理/超时立即停止，不自动重试，保留已产生报告。原产品lease/.5资源释放/调用预算不改。观察器最多8192弱槽、报告仍原4096采样上限。

本轮已执行且仅有：源码/QA/原报告读取、analyze、8个准备单测（0.014s，8PASS/0FAIL/0SKIP），测试使用小型合成图/假snapshot和门禁mock，未调用tracemalloc.start、run_soak、外部子进程或heavy_lock。覆盖只读不改报告、未知层拒绝、无正文/路径输出、weakref不保活、共享对象估算、分配分组、profile默认拒绝、子worker门禁/边界。它们不是未执行profile路径的运行证明；该路径仍须QA与root短对照验证。

root协调锁释放后才可考虑的最小一组（本轮不执行、不要求用户另授权）：

```sh
python3 -m scripts.v2_soak_memory profile --execute-profile --attempts 6 --timeout 30 --output ./memory-controls-n6
```

工具自行获取原重型锁，不要嵌套with-build-lock导致自锁，不创建第二锁。建议先只N6一组，审核完整分母/清理、四点存活与开销，再决定N12或N24，同attempt重复不混数据。无需再跑60分钟来检查工具本身。实际profile未验证前不把命令当可用性已通过；任何未确认退出、分母/计数不等、额外生产对象存活都先保留并定位，不能调大上限或修改产品来刷平。

判读顺序：先确认工作量与清理一致；再看report-held与释放后traced current/弱对象差；再看plain/traced、traced重复、idle的差异（测量开销和噪声）；最后结合contexts/owner done句柄随attempt增长解释Python存活图。若报告释放后生产peer/session/operation仍存活，先给出可复现的具体外部持有链和相同输入对照，才决定生产修复。当前只确认源码持有结构、未确认哪条贡献了原RSS。新TLS每连接总账是另一工具，不能以本批旧队列对照推断其趋势或A36/P14结论。
