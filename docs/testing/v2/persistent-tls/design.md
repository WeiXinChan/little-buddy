持续服务进程TLS稳定性验证准备（非A36/P14完成）

基线main c617cd97（PR114已合），新工具仅scripts/v2_persistent_tls.py、对应fixture/本说明；不修改生产或旧冻结工具。prior-evidence.json只读引用root两臂：release诊断历史后除owner外观察对象归零，但RSS不回落，不能精确归因原48.414MiB。此工具解决“测量者保活历史”与“每轮重启服务”的混淆，不承诺泄漏判定。

推荐执行拓扑（本轮未执行）：

- 监督进程非阻塞取得既有heavy.lock，启动一个独立驱动进程（新process group）；驱动只启动一次服务子进程。服务运行真实voice_server/VoicePeer/auth/scope/bind/heartbeat/ACK，TLS仅127.0.0.1随机端口，合成ASR/模型/TTS沿已有UnifiedProviders。无生产凭据、云factory、设备开关。
- 私有继承socketpair用于合成provider门控及脱敏状态，不对外开管理端口。服务仅保留当前peer和未结束retired任务；已结束任务观察异常即移除，不持有peer/writer/完成task历史。confirmed关闭后释放工具的current引用，不修改生产Peer/Session字段，不强制GC。服务端handler、connection_lost、generation/recognition/visual/retired均纳入有限drain；不确认则保留当前句柄/隔离，不继续连接。
- 驱动复用原TcpRelay、SyntheticSpeech/Model、NetworkMeter和固定七种fault定义，按normal/asr_rst/plan_rst/partial_rst/pause_resume/half_open/playback_stop各带一次正常恢复。最多3轮×14=42连接，固定seed17/顺序，服务从头到尾PID相同，不重启恢复。完整每连接标量账本持续累计，不删除失败或重置计数。客户端只持有当前relay/wire/任务，确认后放弃诊断引用，不保存包、PCM、文本、身份或ACK材料。
- 第一个连接额外走同Session：初始猜谜交付→故事→冒险→新冒险部分ACK后stop→联想恢复；不另增连接。子步骤先登记attempted，失败保留。核对真实game模式、同一constructed编号、stop前后heard不增加/无pending、旧ACK重放不改状态、新scope交付ACK后完成。哈希用于观察状态，不将expected写入provider上下文；合成模型按固定输入产生模式，这不是自然玩法语义质量证明。首连接聚合frames可能大于acks，因包含故意未ACK后续帧的stop子步骤。
- 新连接核对实际session不同；跨连接/stop后的旧ACK通过真实wire发送并在服务处理序号屏障后比对head/heard/game哈希。陈旧epoch音频在驱动侧丢弃，不能称物理扬声器未出音。RST必须实际setsockopt/abort成功，暂停必须实际relay blocked标志；正常恢复有帧、有ACK、heard及close握手。标签不替代字段证据。

采样与判读：服务在自身进程读取/proc，驱动在自身进程读取/proc；report明确service_pid/driver_pid，service/client资源字典分开，不把驱动RSS算到服务。检查点为before_warmup、after_warmup（前2连接，含同Session子路径）、每轮后；均处于无当前活跃session/retired/pending的同类静止边界。只保存有限标量、状态哈希、计数，最多42连接行、5检查点；不保留对象图。暖机包含加载/TLS/额外连续路径，不能把首点与后点差当泄漏。没有人为RSS增长阈值、无连续峰值证明、无trace/native归因、无forced GC。此为最多42连接生命周期稳定性候选，不是60分钟混合有效互动，P14/full_acceptance恒false。

有界执行：服务总180秒，驱动工作170秒，单连接6秒（首连接含额外子路径），IPC3秒、relay/client drain各0.6秒、服务drain0.6秒；产品Session/VoicePeer原TTL、响应预算、0.5秒资源边界均不改。服务共享额度360 model/64 TTS/8192 Unicode字符/424合成单位，失败和重试也由现有Meter扣计，不每连接续期；无真实费用/免费保证。正常退出确认服务exit0；未确认时子进程强制终止仅记作进程隔离，不当作provider释放。外层185秒杀自己创建的process group并写timeout_killed_group，锁不释放到仍有run-owned进程。无自动重试/新服务替代。驱动每连接及最终写result，外层验证失败另写supervisor固定失败码，不倾倒stderr或异常正文。

本轮仅轻量11方法PASS/0FAIL/0SKIP，fixtures.log：默认禁用与范围、1/2/3轮报告42上限和PID分离、实际字段反例、缺采样/类型、监督替身只启动一次/超时杀自有组、确认/未确认peer引用、任务异常观察移除、真实Wire方法的ACK/旧ACK变异拒绝及旧epoch丢弃。所有进程/锁/TLS均替身或未调用，服务/驱动实际连接和42连接可执行性仍未验证；不以这些fixture声称实际路径通过。

待独立QA与root批准后才可运行（本轮不运行）：

```sh
python3 -m scripts.v2_persistent_tls prepare --enable --rounds 3 --output ./persistent-tls-42
```

未传--enable直接exit2；--rounds只接受1..3。先独立QA审查当前引用/有限监督与故障字段，再由root决定有限首跑。真实供应商/ASR/声学/手机、完整60min、账单、稳定平台与原48MiB精确归因均未覆盖。资源失败/超时不续跑，保留已有result/supervisor证据；不能以强制退出后对象消失来宣称正常释放。

PR115独立QA后补强：见qa-fix/review.md及final-tests.log（21轻量方法通过，包含原四反例）。内部子进程必须隔离解释器+真实继承锁FD的FLOCK/PID/inode/角色/source/run核验，FD同时传给service，父验证摘要；正常connection_lost+transport关闭+原socket FD释放才放弃引用。成功终态封闭schema并要求非强制exit0及shutdown见证；同Session新增真实对象weakref与脱敏绑定、首个已播材料/计数延续见证。原11项仅为早期准备记录，不代表本次增加的原生/锁语义已实际执行。仍不运行服务或TLS42。
