独立工具提交，仅显式retain-only-change两轮，不含all、其它case、新局正控或memory入口。固定生产source253ad055a87ca21103e3c95b729874aaeaa7ce28（PR140），复用已审逐例真实VoicePeer/Session/PLAN/FACTS/whole+segment safe、合成Speech和实际Session ACK、心跳/故障与BatchState清理路径。新工具/新pin不进入自身hash；pin只核该生产commit既有backend/scripts/固定帮助文案，工具由独立commit定位。

root审后唯一执行命令，新输出目录，不覆盖旧歧义原样本：
```sh
python3 -I -B scripts/v2_retain_only_probe.py --case retain-only-change --execute --acknowledge-quota-not-live-verified --output /home/ubuntu/tech/v2-delivery/retain-only-change-253ad055-once
```
第一轮固定合成输入：“我们玩会飞的东西，不重复。我已经说过小鸟和飞机，这些不能再用；这次我说蝴蝶，轮到你。”
第二轮：“只改成两个字，保留会飞和不重复，不重新开始；轮到你了。”
这是明确不重开的合成对照，不把原含“我先”样本重新标成确定理解失败。孩子输入自然地声明规则/已用材料，不把离线expect/judge写入provider；模型仍自由生成，不硬编码它要说的词。第一轮若真实完成有效ACK后才继续第二轮；首真正失败/不完整交付/未确认清理停止，不重跑整组或自动其它case。

硬上限16模型请求（2轮*每轮read<=3+safe<=5），原共享一次network/句数/格式repair/CAS/response预算保持，不能以工具拒第二PLAN改产品行为；工具无额外循环或precheck。整组45秒/父55秒/HTTP10秒/max_tokens1400，理论输出token<=22400非账单硬上限。模型固定1017/no fallback；额度ack仅说明未实时核实、既有授权，历史免费控制不伪称当前零账单。真实ASR/TTS/image/手机/部署/长测均禁止；仅合成文本/本地PCM/ACK，默认不执行/不读配置。旧12次/1440字符为合成Speech上界，不是供应商计费。原预算机械停止标签保持，与模型语义失败分开。

result.json记录两轮实际全部完整ACK正文/segments、实际game_before/after（含guess_role如存在）、hidden前后、fixed normalization/failure、模型stage、usage差量/缺失未知、pending/cleanup及transport元数据。admission记录source/额度未知/固定模型，supervisor记录真实exit/forced_exit/验证，不以强杀伪造清理。semantic_pass恒null，root需人工判新增回答是否既符合主题/字数又未用双方旧词及本轮新占用词；不能凭词同时出现判过，不重跑其它已过玩法。未完成两轮artifact_valid应false但原部分材料必须保留。

最终6个离线方法PASS/0SKIP：两轮实际同Session ACK/context/state/usage；首轮safe拒绝停止；第17请求出网前拒绝；禁all/memory/重开及默认无执行；source pin不递归；生产一次格式repair成功（2轮合计3PLAN/2FACTS）仍在16cap且无机械拒绝。合成model不是实际语义理解证据，未调用云。明确新局正控只保留在PR140离线对照，没有新增云组。memory pair保持暂停，待root下一步安排。
