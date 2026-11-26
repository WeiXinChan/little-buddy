本批是A36/P14网络故障工具接线，不能据短回归宣布长稳、设备网络、供应商或声学完成。

固定依赖PR106 head261bc77be3247d5a32fda21506422f778f3eecfc（包含105/104正常集成）；新分支仅改测试工具及证据，不改产品VoicePeer、server、模型适配、预算或原阈值。已读docs/v2-acceptance.md A18/A19/A25/A36与QA network-audit/review.md、review.json、tls_faults.py。QA原两个方法原样收入tests/v2/test_tls_faults_original.py；它们的输入/断言不改。

机器可执行入口：

```sh
python3 -m scripts.v2_soak --transport loopback-tls --offline-seconds 12 --interval .05 --max-attempts 14 --seed 17 --output short.json
```

原默认duplex行为不变。新LoopbackTlsTransport单独入口只构造合成ASR/OfflineModel/TTS，不能传云provider、设备或凭据。临时openssl自签localhost证书/私钥在TemporaryDirectory生成并清除；连接127.0.0.1并以localhost验证TLS，不读真实配置/secret、不做DNS、不公开监听。生产voice_server真实token鉴权、VoicePeer.run/handle/recognize/PLAN/审核/bind/scope/ACK/清理均执行。server类仅在驱动进程内临时子类观察真实dict/set/任务状态，委托生产行为；要求独立进程，不允许与另一个服务或另一个loopback工具同时运行，因为观察patch及安全loop异常处理器为进程级，finally恢复。

场景与时序：

1. 每个故障行后独立正常恢复行，七种触发组成14连接短周期：正常close、ASR probe未seal时RST、PLAN等待RST、只ACK首帧后RST、下行暂停恢复、双向有限半开后RST、部分播放实际stop。四种合成文本主题按固定seed洗牌，预期不送provider。每连接正常scope核对contract/management_v，wake/advance/input/probe/seal/decision→新epoch stop→open/bind→正常identity ACK。heartbeat5秒。合成PCM、合成ASR文本及离线结构化模型不等于真实语音识别/玩法质量。
2. TcpRelay只搬运密文，目标硬编码loopback生产端口，不解析/落盘包。单relay只接受一个连接。每方向一块4096 bytes；StreamReader limit8192、writer high8192、WS max_size16000/max_queue4/write_limit16000。pause门控下一次读取/转发，已有一块可在途；pause_resume须真实观察下行阻塞，恢复后经ACK交付。半开固定50ms后RST，明确不是实际家庭弱网。relay_buffer_observed_max是块+writer缓冲观测，不是整个TLS/内核缓冲总量。
3. 新连接必有新Session；相同player字符串不授跨连接权限。下一连接首帧合法ACK前，通过真实wire重放旧ACK并等待生产sequence消费，核对head/heard/game均不改变。PLAN取消后故意晚返回的离线fixture也不能出音或提交。未确认退出时禁止创建下一连接，原QA证明生产server会拒绝1013；工具额外自身隔离，不循环重连。复杂图片/摘要迟到同时发生仍不在本批组合覆盖内，不据此声称完全排除。
4. Limits沿原约束（最多3600秒、120尝试、45秒/尝试、720模型/240TTS/28800字符；全局Allowance和原ResponseBudget），所有失败/取消/重试在调用前计入全局账。ASR单列合成调用数，不当云额度/费用证明。总连接、attempt、模型阶段、合成预留、RSS/FD/线程/任务观测趋势从运行起累积，重连不清零；全体peer/retired/generation/visual、recognition scopes/capture及server handlers观察峰保留，环形样本淘汰不丢峰。进程RSS不是某连接独占内存，maximum只是观测最大值。场景注入和真实wire事件区别输出，不记录正文、身份、PCM、包或凭据。
5. 取消由asyncio.wait监督实际Task，不把wait_for当硬中断。动态drain覆盖晚注册retired及已完成Task异常；收尾有共同截止，无法确认返回failed/isolated并保留NetworkReport.cleanup_handle（JSON不序列化）。调用方必须保留该句柄/独立进程父监督，不得重用provider/继续下一例；任意吞取消协程不能保证物理中断。默认合成路径无云代码入口。启动openssl最多5秒；尝试监督受剩余运行时长/attempt_timeout限制，另有有限收尾窗口，不承诺操作系统绝对实时硬界。CLI须以独立进程监督运行。

运行规划：不自动执行长时。本批短CLI提前attempt_cap就结束，没有空等补时；duration是上限。root后续若批准60分钟，可按实际计划用--offline-seconds3600 --interval31 --max-attempts120 --seed17（最后自然调度间隔计入standby，不能冒称有效互动）。报告observation_seconds/active_attempt_seconds、wall_60_minutes_observed均如实，full_acceptance/p14_verified永远false。工具切换会话的覆盖不能代替同一儿童长会话、设备业务驱动、真实供应商网络及账单。旧session79841未干预。

证据：final.log为32方法32PASS/0FAIL/0SKIP（7新增、QA原2、原TLS1、read_retry9、原soak8、采样5）。随后只因增加真实server/recognition观察计数，复跑7新增为metrics-corrected.log，不把重复方法相加。cli-short.json是最终真实CLI合成短跑。原QA两个反例保持原输入断言PASS；无独立突变宣称。

初版initial.json中PLAN RST后被工具将预期ConnectionResetError误算清理错误；随后relay按网络事件显式计数。tests-initial.log还记录过早握手取消时监听accept收尾竞态/资源warning（不能以unittest绿掩盖）；修复为等待真实accept回调、有限回收，握手ConnectionResetError以固定枚举记录。未知loop故障一律关闭后续allowance并隔离，未吞为PASS。tests-second.log保留中间握手reset日志。final.log/metrics-corrected.log没有该未处理错误或资源warning。新增计数首版误用其他websockets版本的handlers接口，collector关闭allowance导致CLI单次timeout，cli-api-mismatch.json及中断的metrics-final.log保留；读取锁定17.4实际Server源码后改为handler_tasks，7方法修后通过，最终CLI14连接全部清理确认。冻结前增加SO_LINGER实际设置成功检查，故障行必须rst_applied=true，否则失败；frozen-seven.log为最终7新增方法7PASS，不与32项重复相加。cli-short.json是在该元数据检查前的同路径14连接短跑，不伪称记录尚未存在的字段。
