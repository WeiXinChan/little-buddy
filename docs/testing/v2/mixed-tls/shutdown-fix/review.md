PR116 shutdown终态增量

root原两反例已复现（active=true/quarantined=true均被旧验证器接受）。root-original.json为root原结果原件副本；original-inputs.json保留修前完整两份变异输入，original-reproduced.json保留本地修前结果。修后同字节输入均拒绝，见original-replay.json。针对新版完整正控也逐字段变异，避免仅因旧fixture缺少新增字段而拒绝。

只修改报告验证，不改生产/状态生产者，也不在运行时机械补预期值。shutdown取MixedService.state()真实快照：peer已确认释放后active/quarantined/generation/same_session/recognition_active必须严格False，finished严格True；pending/retired/errors/heard/pending_audio/played_count/capture_bytes/asr_active/tts_active必须严格整数0（拒bool/string/unknown）；binding/played_anchor/state_hash/game/rules_hash/roles_hash为None。服务PID/start_ticks须与最终采样同源。

constructed不直接从尝试数填入：各连接先有独立Session binding及确认release；release.constructed必须是实际顺序1..N、finished=True、same_session=True且binding匹配该连接。shutdown.constructed须等于最后实际release值。现契约已要求每个成功清理行（包括最终cutoff）有真实binding；无法证实admission/关闭时保持失败，不推算/补造构造计数。

12唯一方法PASS/0FAIL/0SKIP（受影响旧7+新增5），tests.log。涵盖原两输入原样拒绝、完整正控、23组单字段负控、缺字段、bool-as-zero/未知类型、release/constructed/绑定矛盾、以及不创建服务进程时实际MixedService.state()无当前peer的正常状态语义。后者是内存对象/本进程元数据fixture，不代表原生服务已验证。无实际服务/锁/worker/TLS90/TLS3600/云/设备/部署，不重复旧全集。

原42连接证据/PR115冻结head不变，完整A36/P14仍OPEN。此修复只关闭终态验证缺口，等待独立QA审查后由root决定短实跑。
