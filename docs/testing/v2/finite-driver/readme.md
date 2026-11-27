# 固定单 case 补验驱动

依赖 PR144 的 `v2_cold_query_preparation.py`（本工具提交不改它）；产品 source 固定 `8682f5a567ddadae1f717cab8d706d6b4ee52316`，backend/v2 等价 fe49。独立工具 pin 包含现有完整 source manifest 以及复用 harness/本工具/seed 的 SHA256；不互相递归 hash。

默认只打印禁用计划：

```sh
python3 -I -B scripts/v2_finite_probe.py --case body-danger
```

root 首批唯一执行命令（本作者未运行）：

```sh
python3 -I -B scripts/v2_finite_probe.py --case body-danger --execute --acknowledge-quota-not-live-verified --output /home/ubuntu/tech/v2-delivery/finite-body-danger-8682-once
```

可选值仅 body-danger/death-danger/shared-intent/cold-query，无 all、自定义输入或自动下一组；其余 case 待 root 判读前组再选，分别用独立未存在输出目录。body8/death8/shared16/cold8 模型请求上限；组45秒、父55秒，12次合成TTS/1440字符、每请求32768B、模型输出1400token及既有规划预留。无模型 fallback、无工具自动重试；生产共享一次读 retry/修复、原 CAS/响应预算保持。每轮读阶段共≤3、review≤5，上限8；整段审核始终保留，多句才增加逐句审核，单句复用整段审核，不改变生产门禁。用量 before/after delta、缺 usage 未知均沿既有工具；额度未实时核验，历史用户用完即停截图不等于实时余额/零账单保证。

只允许真实1017文本；只读既有 `/etc/little-buddy-v2/service.env`/凭据路径，配置模型不一致即停止；真实ASR/TTS/image均0。输出新建0700目录，result/admission/supervisor分开：固定合成候选、模型可见 context、whole/segment候选及严格 allow/quality、实际已ACK文本/state/隐藏答案、usage/阶段耗时/固定失败诊断/cleanup。原异常消息、供应商原文拒绝理由和凭据不记录。此脚本是固定合成新会话工具，不可用于任意用户历史。

危险第二轮在生产input_policy门禁即固定帮助，离线已证0provider/0TTS/0ACK。报告如实 `local_help_protocol_only`、`protocol_emitted=true`、`device_playback_confirmed=false`；不会为追求final ACK调用模型或伪造播放。父验证该协议履约可完整；正常首轮必须真正最终ACK，不能拿帮助替正常身体/死亡解释。`artifact_valid`只表机械证据，不是语义PASS。任何正常轮失败即停止，不下一轮/下一组；合法危险帮助是该固定case末轮，没有后续自动操作。

cold-query：ColdPeer只在构造阶段接收 prepare 返回的**同一个Session对象**，之后由生产VoicePeer、heartbeat、bind、PLAN/FACTS、review、ACK推进。70个背景是合成seed，不计模型完成/云工作。seed保留归档目标完整记录及archive哈希、实际hot facts/recent/heard、压缩与来源计数。query不含答案；trace保留实际PLAN context中的精确source_id/source_text，父验证同Session绑定、来源不在hot/recent/heard、实际审核通过及最终ACK。不会重填答案或将expected发模型。语义是否正确使用否定/偏好仍须人工判读。

离线6项PASS：默认禁用/拒all/pin；两个危险第二轮0provider；首安全失败不跑后续；真正冷档同Session→PLAN→整段/逐句审核→最终ACK及来源/绑定篡改负控；生产一次repair仍可用、额外第三PLAN被Meter阻止；复用原safety负控禁止任何audio。初次5项有1FAIL：测试误要求单句重复逐句审核；原日志保留，改双句fixture证明实际整段+逐句记录，未改产品审核。脚本化模型仅证明接线/契约，不声称真实语义已通过。

离线命令：

```sh
python3 -m unittest tests.v2.test_finite_probe tests.v2.test_m05.Integration.test_safety_negative_control_prevents_any_audio
```

本轮0云/设备/部署/长测，不建立服务，不触heavy.lock。
