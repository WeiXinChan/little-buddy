## PID12482：结论仍为 UNKNOWN

线上参考源码 `98a1ce18ee5e75b5ea4f993211e4fdf632e703fb`。root 转交 TITA101 run `01a22044-e788-7c19-848e-82ec71ee5fd2` 手机内部 monotonic 毫秒：

| 事件 | 手机单调时钟 ms |
| --- | ---: |
| PROTOCOL READY | 202316083 |
| CAPTURE_READ READY | 202317875 |
| WAKE_ACCEPTED | 202332093 |
| wire FAILURE / SERVER_TIMEOUT | 202362075 |

同机相减：wake→failure=29982ms，protocol ready→failure=45992ms，capture ready→failure=44200ms，protocol ready→wake=16010ms。随后 HOLD/释放是观察到的终态，不证明触发源。不与服务端时钟相减。该记录无法关联到用户哪次表达，缺少服务端最后 speech 接收/age、heartbeat 接收、probe/endpoint/seal/open、首有效 ACK 和 terminal 分支。PID8260 合成测量无 wake、110.569s 截止，不能与此进程拼接。

## 可复算边界（全部为服务端同机 monotonic）

| 路径 | 条件与原行为 |
| --- | --- |
| monitor 第一处 | `awaiting_input` 且非 THINKING；`input_budget.remaining()` 在无 anchor 或 `now >= anchor+15+thinking_seconds` 抛异常，撤销后发 timeout。speech anchor 为接收时刻减 age_ms，仅更新到较新的真实 speech 边界；quiet/probe/seal/heartbeat 不续时。 |
| input analysis | ASR 与 endpoint 串行受同一 remaining 的 asyncio timeout；供应商自身 TimeoutError 也可提前失败。过期仍发 timeout，不能转 unknown 获得新预算。 |
| monitor 第二处 | session `_live` / `poll` 后 inactive 或 response_expired，发 timeout。heartbeat_deadline=最后被服务端接受 heartbeat+15；有效 heartbeat 不续 response 或 TTL。正常 session TTL=最近有效交互+600，单独正常 TTL 走 session_end 而非 timeout；管理暂停到期仍属 timeout 分支。 |
| 输出首有效 ACK 前 | response deadline；stop/open 从 prepared 继承原输入 deadline，不能从输出启动再给15s。未 bind、无首有效完整 segment ACK、生成卡住等均可能到此边界。 |
| 输出首有效 ACK 后 | `progress_deadline=last_head_progress+60`；有推进的 ACK 才续60，重复 head/heartbeat 不续。reply_end 完成清零 deadline，正常沉默不再受旧输出 budget 约束。 |
| 输出异步工作 | owned 等待及供应商 TimeoutError 也可由 `_respond` 发 timeout；wire code 并不区分源。 |

`VoiceClient.kt` onOpen 在 Handler 上立即 heartbeat.run，此后每5000ms postDelayed；send 经过 active/permitted/socket/queue 检查。服务端处理成功才续 lease。这个实现不证明 PID12482 当时真的发送/服务端收到每次心跳。客户端 failure(code=timeout) 经 ServerFailure 映射 SERVER_TIMEOUT；本地 response deadline/playback 错误有另一来源，不能混同。

若服务端调度、传输无大延迟：始终没有任何 heartbeat 的连接应约15s而非46s结束；固定 wake 后15s输出卡住也不直接等于30s。30s仍有多解：较晚真实 speech 后15s、较晚最后 heartbeat 后15s、或异步供应商自身超时。首有效 ACK 之后才启动的完整60s进度预算，在该 ACK 不早于本次 wake 的前提下，无法单独解释 wake 后30s；此前未完成输出/调度停顿则需独立证据。手机收到 failure 的时刻包含传输与调度，不能倒推出服务端最后 heartbeat 或 speech 的绝对时刻。

## 最小诊断补丁（不改变决策）

沿用默认 OFF 的 `--observe-failures`，不新增开关、wire 字段、重连规则或供应商请求。bounded_failure 加固定 stage=timeout，source 仅 input_monitor/session_monitor/input_analysis/output_generation；记录同机采样的 input/output/progress/heartbeat/TTL 剩余毫秒、固定 expiry 枚举、awaiting/thinking/confirmed/expired/active 布尔值。无 deadline 为 null（绝不作0）；负值表示已越界。session_monitor 允许在 session 过期后记录，但仍要求原 peer/session 对象和 connection 匹配；这只获得诊断资格，不获得 Operation 发布权。

沿用且共享进程900s、最多4 peers、每 peer4条、总16条上限，timeout 不重置窗口；原 provider bounded_failure 与 timeout 可能各占一条。窗口已过、名额用尽或诊断未启用时无记录不代表无故障。sink 异常使 observer 关闭，不改变 timeout/清理。没有音频、文本、session ID、URL、密钥、错误正文。根因缺口：精确最后接收 heartbeat 的序列/事件未逐条存储，仅终态 lease 剩余量；下次也必须先确认窗口确实有效。

root 审核后才决定是否在既有部署流程使用该补丁；本轮没有启用、部署或重测。回滚为原源码或关闭既有 observer，不需要 APK/模型/wire 变更。

## 离线验证范围

`tests/v2/test_timeout_boundaries.py` 复用现有完整 ACK driver，执行生产 VoicePeer.run/monitor/handle、JSON wire 与受控时钟，供应商为本地 controlled fixture；stream_asr OFF/ON 各覆盖正常静默到50s、失联心跳精确15s、无probe输入精确15s、卡住endpoint、不削短 THINKING、未bind输出精确原deadline。独立 observer 测试覆盖共享额度/900s/connection隔离、默认关闭、sink异常。既有 `test_m04` 检查首有效/重复ACK与60s progress，`test_failure_observer` 包含真实 localhost TLS/ACK 与异常sink回归。没有模拟现场的用户语音或证明真机根因；本轮未复现新的产品控制缺陷，因此只补诊断，不改时限/恢复策略。原code33第二 SERVERVOICE 仍 OPEN UNKNOWN。

复现命令（仓库根目录，原2GB cgroup构建锁，串行）：

```sh
sudo -n scripts/with-build-lock python3 -B -m unittest tests.v2.test_timeout_boundaries tests.v2.test_failure_observer tests.v2.test_m04 tests.v2.test_post_solo_probe tests.v2.test_stream_asr
```
