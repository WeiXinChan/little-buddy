PR114 TLS14-01/02/03 修复交接

父验证不再按标签认定完成：逐连接验证RST/暂停实际标志、恢复交付帧/ACK/已听记录、新session及旧ACK拒绝、关闭确认；attempt与最终ledger的稳定字段必须一致，原legacy网络错误计数仍允许单调增加，不改原报告。采样必须具有时间、合法阶段、完整资源指标、每连接活跃及清理覆盖、最终零在途和可复算趋势；maximum仍只是观测最大值。

子进程超时、非零退出、验证失败停止本臂，不自动重试。保存已有完整artifact及child-evidence.json/result.json：固定终态类别、exit/timeout元数据、白名单phase/cleanup。诊断最多取末64KiB/128行/32条，丢弃任意正文、stderr文本及异常文本；缺字段/错误类型统一拒绝。普通成功JSON也不能凭部分字段成为成功。

原独立反例完整保存为independent-original.py，原四FAIL在original-failure.log。QA原setup依赖旧作者快乐fixture；为保持其原负例输入，original-seeds.json冻结了旧setup的三臂输入。replay仅替换setup为读取这些字节，继承原四个test方法、变异及assertions不改。新快乐fixture使用完整合成资源/交付结构；另有单字段负控防止原负例因其他缺字段而偶然被拒绝。

实际执行：18方法PASS、0FAIL、0SKIP，final-tests.log；其中8原准备方法、4原反例复跑、6新增方法（含多组subTest）。仅替身archive/process/lock、合成JSON/小对象，无TLS14、worker、profile、tracemalloc负载或heavy.lock访问。initial-after.log保留开发中缺字段KeyError的3ERROR，随后统一转为Rejected；不覆盖原失败。original-import-attempt.log为首次缺PYTHONPATH的导入失败，亦保留。

冻结c486源码、原一小时报告及原计数不改。14连接是七种模式各带恢复的一轮，不是14轮故障恢复。玩具owner释放检查已由QA通过，本次不修改对象所有权。保留原RSS+48.414MiB、归因unknown，不以本次fixture宣布实际测量可用、A36/P14完成或内存稳定。真实TLS14仍须root另行批准。
