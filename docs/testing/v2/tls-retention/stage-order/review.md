TLS14-02 阶段顺序增量

保留QA独立independent_boundaries.py原件为independent-original.py，不改输入/assertions。修前3方法2PASS/1FAIL，修后原样3PASS，分别见original-failure.log/original-replay.log。

冻结c486的attempt()依次发出attempt_started、initial(构造ObservedPeer)、before_network_fault、after_network_fault、before_transport_cleanup、after_transport_cleanup、attempt_finished。ObservedPeer.run finally另发一次after_transport_cleanup，因此合法清理标签为一次或两次，均须位于before_transport_cleanup之后、attempt_finished之前。仅校验这些锚点有序，不固定总样本数；operation/periodic/retired等可重复穿插。窗口首尾与原attempt时间双向绑定，保留原20ms元数据舍入容差，不改产品期限。

最新22唯一方法PASS/0FAIL/0SKIP：原18项+4时序项，包含相邻锚点反转、矛盾重复、重复active/periodic及两次cleanup合法、提前cleanup拒绝、窗口时间脱离拒绝。QA原3方法另行原样复跑，不与22项合并扩大分母。

只读历史117连接/2119采样PASS，全部117条合法+2计数PASS；历史实际ASR窗口内存副本只交换故障前后标签已拒绝。原文件字节/hash不变，见historical.json。未执行TLS14/worker/trace/锁/云/设备/部署，不改冻结c486/原报告/所有权；RSS归因仍unknown。实际14连接为七种模式及恢复的一轮，仍等待QA/root另行许可。
