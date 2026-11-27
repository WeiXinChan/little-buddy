A36/P14 持续混合互动准备（待QA/root批准实跑）

原要求：v2-acceptance.md A36 为“60分钟混合互动，网络扰动、反复打断和换玩法；无持续资源增长/旧任务堆积，记录延迟及上下文随时间变化”。v2-requirements.md P14要求自动化持续稳定性；R17不允许用费用/安全捷径掩盖无效工作，R18不把过程测试交给孩子/用户。此工具只准备后端合成层证据，不宣布完整A36/P14通过。

基线main fd843b046fcd0a5033f938a6894ccc60499fbddd，显式依赖已合PR115。只读引用QA的PASS_SINGLE_BOUNDED_PERSISTENT_TLS_RUN及原结果hash，见prior42-reference.json。旧42连接实跑2.7秒、暖机后RSS+2.390625MiB，不据三轮增量变小宣布平台；本轮未重跑或改写其证据/冻结head。

实现与最小复用边界

新scripts/v2_mixed_tls.py提供单一持续服务子进程、分离驱动和监督进程。复用真实voice_server/VoicePeer/Session、统一provider、本地TLS、scope/auth/epoch/bind/heartbeat/ACK及同一个TcpRelay。PR115脚本只增加三个默认兼容接缝：internal_authority可显式绑定新入口program；serve_child可显式传合成Service工厂/本轮lifetime；Wire ACK前后空钩子供新模式节拍。原入口默认参数、180秒/42连接、额度、校验及产品0.5秒释放/TTL均不改；原21轻量准备回归仍通过。没有产品/Android/部署修改。

继承原真实同FD的heavy.lock/FLOCK/PID/inode/source/run/隔离核验，将FD继续传给服务；没有第二锁或默认执行。一个服务PID及其/proc start_ticks在每次采样时实际读取（非只抄启动字段）。服务仅保留当前peer、当前原socket观察句柄和在途retired；确认handler/connection_lost正常、transport关闭及原FD=-1后才放弃引用。不保存完成peer/writer/task历史、不强制GC、不失败重启新服务刷平。报告数组只在驱动进程，资源开销与服务分开。

完整3600秒工作计划

- 固定seed/顺序，不扫描参数。每连接先同Session完成猜谜、故事起始、改两句规则、承接蓝星上下文、太空探险、交换角色、联想七轮，再部分ACK后stop、同Session恢复一轮，最后一轮进行指定真实fault；共最多10次尝试/连接。实际Session对象/绑定、已ACK材料hash/计数及规则/角色hash来自生产Session；合成模型对承接/角色交换请求要求真正前轮context存在，expected只在驱动判据，不进入provider上下文。合成模板不是LLM玩法/安全语义质量证明。
- 偶数连接依次asr_rst、plan_rst、partial_rst、pause_resume、half_open、playback_stop、normal_close，奇数连接为新Session正常恢复。每14连接一轮七模式及恢复，服务不重启，连接/turn/round/calls总账不重置；42连接旧证据与此处的多轮真实节拍不能混称。最后可能为未完整的一轮，原样保留。
- 每条输入明确合成6秒16kHz/16bit/单声道PCM，300包×20ms；每包实际发送后至少等其20ms节拍，不用批量瞬发后空等。有效输入只按已完成节拍的样本计，另报实际sent样本数；中断最后一包不补记有效时长。合成ASR根据固定公开文本fixture返回，并不识别这些波形，不冒充实际ASR/童声/端点能力。
- 每回复声明2秒24kHz PCM，20包×100ms；通过真实TTS资源/VoicePeer流式发送，驱动按各包真实bytes/48000延迟当前ACK，只有发送ACK后才记simulated_ack_playback_seconds。未ACK段、旧epoch、占位、任意sleep不计有效播放。生产最后帧ACK后才能提交状态；实际speaker/设备出音未覆盖。
- 单调钟工作窗从驱动开始计3600秒，持续提交下一轮，不按30秒空隙或standby补满。只有本工作窗自己的timeout确实expired才允许最后一轮记duration_cutoff；内层响应超时/普通失败不能冒充计划结束。所有尝试在获取资源前登记，取消/失败/截止都保留；不重试刷绿。达到调用/连接上限却未到时就是失败，不空等。

预算与预期量（估计不是实测/账单）

固定最大70连接、720轮、3600次模型调用（endpoint/PLAN/FACTS/安全/摘要/重试全计）、720次TTS、20000 Unicode字符、4320合成额度单位，服务期统一Allowance从启动到结束共享；配置新轮不续期/归零。无真实模型/语音/图片provider入口，真实费用unknown，不能用合成单位或免费额度声明≤3元/小时。

纯媒体下每完整连接约76.1–78.2秒：输入10×6秒，8次完整交付约16秒，部分stop约0.1秒，末fault的播放0–2秒。14连接约1084秒，60分钟约3完整模式轮及部分下一轮，约44–46个完整连接及最后截断、约440–470次尝试；实际处理/网络/调度开销会降低工作量，不预填通过分母。约45–47分钟声明输入、约12–14分钟模拟ACK播放，余下处理/网络/清理/静置按实测分账，不承诺这些估计凑成60分钟。预计约2200–2900模型请求及约400余TTS，实际严格按meter，3600/720上限包括失败；如果上限提前耗尽，报告失败而非继续无计量。

所有产品每轮原ResponseBudget/lease/TTL原样执行；工具单轮15秒，只是取消保护而非延长产品预算。服务工作期+20秒清理，监督工作期+40秒；未确认释放保留句柄，有限进程隔离写forced_exit/cleanup=false，不把kill当正常清理。仍是同一旧heavy.lock。

采样、延迟与判据

服务和客户端分别读取自身RSS/FD/thread/asyncio_tasks；每样本带双方PID/start_ticks。5秒周期+真实输入开始/结束、首音频、交付、stop、清理前后、暖机后、每块/每轮与最终事件；上限8192条标量，不保留对象图。原生task/retired/generation/ASR/TTS/capture状态取真实当前状态；采样错误必须失败，不能默认为0。每条turn有时间、输入/播放量、帧/ACK、首传输延迟、scope和上下文hash，完整round账本是14块的连接/turn范围，不删失败。

时间线按input/playback/processing/idle/network/cleanup独占累计；processing是驱动等生产处理/协议的墙时，不是推断CPU忙时。媒体秒数来自PCM样本/实际ACK操作，独立于墙时；校验两者及各turn加总一致。首音频为TLS客户端收到有效PCM的传输时间，不是实际ASR到speaker的P12/P13证明。

保留后段原始标量序列及静止边界：before_warmup、首完整块后after_warmup、各after_cleanup/after_block/round_completed、final。分析时分别看暖机后同类静止点及活跃相位；可按10分钟段查看后半段RSS/FD/thread/task变化，不比较不同相位就断言增长，不据递减斜率宣布平台，不造RSS放行阈值。周期样本有最大10秒缺口门（5秒计划+IPC/调度容忍）；不固定样本总数。静止/周期点不是连续峰值。最终仍需独立审计A36“无持续增长/旧任务堆积”，报告acceptance恒false，不把duration_collected当验收通过。

必要短检查（本轮不执行）

独立QA先审查代码/28项轻量结果。root随后可批准一次90秒单服务节拍检查：

```sh
python3 -m scripts.v2_mixed_tls prepare --enable --duration 90 --output ./mixed-tls-short
```

目标是确认真实节拍/15秒每轮预算兼容、同Session规则/角色/stop与首次ASR RST清理、新Session恢复第一轮、周期/事件采样和同一服务PID/starttime。预计首块约76–80秒，剩余时间恢复与计划截断；不是七模式覆盖或60分钟。若失败保留原件，不自动重复。其他paced故障组合仍未实测。

短检查和QA获root批准后，才决定一次完整长测：

```sh
python3 -m scripts.v2_mixed_tls prepare --enable --duration 3600 --output ./mixed-tls-3600
```

本轮只静态/轻量fixture：新增7方法+受影响PR115原21方法=28PASS/0FAIL/0SKIP，包含fake-clock字节节拍、空等不计媒体、真实上下文缺失拒绝、报告反例、共享额度及合成PCM精确尺寸。没有实际服务/TLS90/TLS3600/worker/锁/云/设备/部署。真实供应商网络/ASR/LLM质量/安全效果、声学/设备、账单与完整A36/P14继续OPEN。

PR116终态增量：见shutdown-fix/review.md。父验证要求真实shutdown的active/quarantined/finished、所有在途及材料残留和Session绑定处于正确无peer终态；constructed绑定逐连接实际release顺序及绑定，不按尝试数补值。root两个原始输入保留并原样拒绝；本次12针对性方法通过（旧7+新增5），未执行原生服务或短/长测，原28项为前次准备证据，不重复扩大分母。

M116关联/媒体/事件/截止增量见association-fix/review.md：生产者增加实际sent/paced/capture/received/ACK样本与头位置、活动/状态快照和取消首时刻，父逐连接逐轮关联及完整固定媒体量核验，不以旧fixture缺字段替代关闭证据。新完整正控先通过后做同类单变异；原五FAIL源码/输入/断言原样保留。最新51项轻量方法通过，无原生服务/90秒/长测，仍待QA/root批准。截止观察+1秒、有限清理+15秒只是元数据有效性门，不改原响应/TTL预算；不确定admission/退出保持失败unknown。
