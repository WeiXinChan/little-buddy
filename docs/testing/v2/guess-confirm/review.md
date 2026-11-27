独立guess-confirm工具，显式依赖PR136生产修复head 521c6cd7cb5a8746496c447732b62fac7879c4bb，复用PR135最终驱动48011e8的生产路径及预算。仅工具与离线检查，不修改PR135/PR136原证据、产品或部署；无云调用。

命令（root审后一次运行；新目录，不能覆盖旧FAIL）：
```sh
python3 -I -B scripts/v2_guess_confirm.py --case guess-confirm --execute --acknowledge-quota-not-live-verified --output /home/ubuntu/tech/v2-delivery/guess-confirm-521c6cd7-once
```
默认不执行，只接受guess-confirm，无其它case/all/外部输入/session选择接口。SOURCE和逐文件pin锁定a3ed0ea生产backend/scripts/固定帮助文案，pin只含该基线既有文件；不把新工具或新pin加入自身哈希，避免递归。工具字节由本提交SHA单独定位，不伪造为旧source的一部分。

同Session严格三轮：首轮自由出家中物品谜语，不指定答案；第一轮有完整ACK文本、final segment实际ACK/public state提交、无pending且状态成功，核仍是本run新Session digest后，仅读取这个Session.secrets.answer。必须非空str、<=64字、无控制字符且与首轮完成后hidden快照一致。此时才构造“是<实际answer>吗？提示它有什么用。”，不提前构造第二轮；missing answer/换Session/未ACK拒绝并停止，不猜默认杯子。第三轮原“现在由我问你猜：能照亮房间的是什么？”。answer只作为孩子本轮合成猜测text进入生产PLAN，不加expected/correct标记、不改原context或直接提交答案。原模型/严格校验/事实/整段与逐句safe/Session ACK不变。

输出实际synthetic_input、dynamic_synthetic_guess标记、synthetic_hidden_before/after、完整ACK/state/failure/cleanup/usage差量，semantic_pass=null；不会说预设答案，不读取任意用户会话。人工仍须确认：首轮线索相符且未泄底，第二轮猜中不否认且确认/用途与同一谜底一致，第三轮角色交换且旧secret清空。离线model仅验证生命周期/构造，不能证明真实模型语义。

保留生产共享的一次read retry/repair，不由harness添循环或禁第二PLAN。每轮read合计<=3/safe<=5，三轮24模型请求，45秒组/55秒父/HTTP10秒/max_tokens1400；原response预算、CAS/revision/清理/故障首停保留。无fallback/整组重试/自动其它case；预算机械停止与模型失败分层。真实ASR/TTS/image均禁止：固定合成text、本地PCM/ACK；真实仅现有1017文本模型和其safe，不切模型。quota acknowledgement只表示额度未实时核实、既有授权，历史用完即停不伪装实时余额或零账单；规划费不是账单。

4项离线方法PASS/0SKIP，0.126秒：两个不同自由合成答案经实际新Session产生→第二输入正确→第三清空；首轮无answer只1PLAN/1轮就停；实际Sink不ACK+短外层期限后仅1轮、无第二输入；严格source pin及默认不读配置/不执行。无ACK检查仅测试将组期限收短以免等45秒，没有改生产lease/预算。未云/设备/长测/锁/部署，不重跑G02/G05或旧真实失败。

更新到guess_role修复head521c6cd7的独立工具提交：game前后审计含guess_role，逐轮记录固定guess_normalization，明确模型原本返回错误secret被清理的情况；旧a3ed实测猜中PASS/第三轮漏答FAIL仍保留，非重写旧结果。仅root随后一次复验，author无云。
