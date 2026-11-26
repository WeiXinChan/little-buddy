# SOAK101-01采样HOLD增量

旧head0bc3c57下QA原3方法原样复跑2PASS/1FAIL：实际VoicePeer generation_scopes见证1，报告maximum=0、sample=[0,0]。原QA源码/日志/报告与本次before.log分别保留；原输入/assertions未改。修后同脚本3PASS，见证1/观测maximum1。

修复仅scripts/v2_soak.py及定向证据：给本runner的真实peer.generation_scopes字典和retired_tasks集合加保持原语义的观测容器，在生产实际set/pop和add/discard之后同步读取transport.sample()与真实proc资源。没有往operation/retired状态造条目、没有按事件名写死active=1；即使手工发operation_started事件但实际集合为空，样本仍0。生产VoicePeer源码不改，register/unregister/cancel/ACK行为不变。

新增attempt开始/结束、超时或外部stop取消前后、transport清理前后、owner清理后及final生命周期样本；周期采样保留且在transport有限清理期间继续，随后取消并回收。operation进入/退出同步采样覆盖无await的短操作，retired集合增减也按真实状态观测；RSS/fd/thread则仍只是这些时点的实际读取，不能证明捕获连续物理峰值。

ResourceCollector使用4096条ring保留样本，同时独立维护所有已观测样本的first/last/maximum，淘汰活跃行不丢已观测maximum。每项maximum_kind=observed_sample_maximum，sampling.continuous_peaks_known=false；不是连续峰值保证，不用idle轨迹冒充活跃证据。采样相位固定枚举，未知相位unknown，不落原错误文本；采样异常关闭下一次I/O门禁，sampling.valid=false且resource_collection_valid=false。资源不可读保留null和missing_metrics，未确认清理/已有失败也不能resource_collection_valid=true。P14/full_acceptance仍false，不用该诊断字段替代业务验收。

5新增+原21作者/受影响方法=26PASS，QA原3方法PASS，共29唯一PASS/0FAIL/0SKIP；编译/diff通过。新增涵盖无await实际活跃观测、容量2 ring淘汰后保留真实max、真实吞取消造成retired/pending增长及清理隔离、采样异常/资源unknown、事件不能凭空造active。stubborn资源finally明确释放回收。0.2秒fixture独立保存，不冒称60分钟。

原时长/额度/计量/standby等待/取消隔离边界保留；只读采样有成本，时延记录包含其实际成本，不声称零开销。本轮0云/手机/60分钟/部署/重型构建/子agent。仅准备采集工具，独立QA关闭后才可供root长测；A36/P14真实设备业务/TLS/ASR/声学/计费/语义缺口继续OPEN。
