# M02 合成测试工具

TITA-80，范围为测试双件和证据约束。依赖 PR #31 的 M01 head `c9270fb2fab75a1efd7809f9913dc51d9d02bdbb`；PR base 选其分支 `agent/agent/f3ceec854fea`，本 PR 只审新增工具和记录。M01 合并后应由交付者核对并重定向 base，不能自动合并。批准三文件不改写。独立评审原文在 `docs/reviews/review-tita-93.md`。

在仓库根目录用 Python 3.10+，无需安装依赖、网络或构建：

```sh
python3 -m tools.v2_harness.run --out docs/testing/v2/self-test.json
python3 -m tools.v2_harness.r94_check --out docs/testing/v2/r94-controls.json
python3 -m tools.v2_harness.inventory --help
```

运行器只执行工具自测，不接受将自测转换为产品 PASS 的选项。`self-test.json` 的尝试数按 unittest 方法计数，subTest 内多个反例不额外冒充产品样本。失败或异常返回非零。报告含 HEAD、dirty 状态及实际工具/对话输入逐文件 SHA-256；dirty 为真时不能把结果归于 HEAD 单一版本。报告本身不包含在工具哈希内，以免自引用。工具自测不关闭 F 项；A01–A38 初始一律 NOT_RUN，产品尝试数为0。

`lab.py` 提供可控 UTC/单调时钟、稳定同刻事件队列、重复/乱序/迟到注入、六维身份与顺序校验参考双件、取消与关闭失败、有界队列、一次重试且总预算不变的网络/额度/超时分类。播放双件支持段前缀、重复 ACK、半段、flush/stop/重建/回绕/路由失效与流代际。权限和删除双件仅表达测试假设，不是拟上线的安全实现。

`dialogues.json` 有10条自造片段和预期意图，无真实完整会话。`write_signal(path)` 生成单声道16kHz一秒PCM工程信号：静音/音调/停顿/音调，各4000样本；返回来源与区间。它不是语音合成器，不支持据此测ASR、童声、多人或自然度。后续合法TTS语料必须保留供应商/版本/生成参数/许可/起止标注，D05未核实不连接真实服务。

`evidence.execute(adapter, case, oracle='fixture.stop.v1')` 仅执行已注册的合成停播场景（`case={'scenario':'fixture.stop.v1'}`）。观测必须恰含严格bool类型`muted`；空dict/list、额外字段、缺适配器、异常和错误未静音均失败。oracle采用工具内固定断言，拒绝调用方传入函数（包括无条件True）。返回观测不是产品执行凭证。

R94-01修正：`validate_report_schema`严格检查attempts/failures/errors/timeouts为显式非负int且拒bool；PASS要求attempts>0，失败/异常/超时均0。后三项为互斥结局，其和不超过attempts，重试单列不能重复扣分母。声学标记必须严格bool并与受控`SCENARIOS`逐项一致（当前A02/A06–A09/A13/A32/A35/A36需要），报告作者不能豁免。该表是证据门的最低范围，不能代替A场景的具体审查。NOT_RUN禁止非零样本。

**当前`validate_product_result`拒绝全部产品PASS**，包括结构完整、版本和哈希字段齐全的伪造行。真实产品适配器、可信实际执行凭证与独立产品oracle绑定均未实现；字符串存在、hash存在或fixture返回正确值都不能替代。后续经独立审查接入之前没有解除选项。`validate_report_schema`仅校验结构，不得用它宣称产品通过。

## 盘点脚本审定边界

本轮仅执行帮助入口和模拟测试，不调用真实adb/system_profiler、不占手机。允许命令仍为`adb -s SERIAL get-state`、四个固定`getprop`、Mac `system_profiler SPAudioDataType -json`，没有新增权限或查询。每个子进程10秒、shell=False、stderr丢弃；stdout最多64KiB，超限/超时终止本次精确子进程并unknown，不输出原始异常。最多6次顺序调用。已有ADB连接/授权及可信PATH是前置，adb本身可能启动主机server，不承诺无任何主机副作用。

R94-02修正：报告最大4KiB（另加换行），音频设备至多16个、枚举匿名编号和白名单输入/输出通道数、采样率；不保留名称、UID、序列号、地址、原始JSON或其哈希。ADB只输出已知状态、PKW110、有限格式Android版本和SDK；构建标识仍按原白名单查询但不保留值，unknown。空输出、未识别形状/值、失败均unknown。设备能力来自可解析系统声明，不证明可用声学路径；未知机型/格式保守unknown。所有原始采集内容仅限有界内存。

由协调方审定后单独串行安排：确认目标设备、V1保护与签名策略、设备可操作性、可编程外放、独立手机输出观测、共同时间基准及误差。脚本刻意将这些能力标为NOT_VERIFIED；ADB连接和声卡枚举不证明声学闭环。没有程序化证据的字段保持未测，不安排用户点按或录音。

## 证据与限制

工具自测结果见 `self-test.json`；完整执行命令、环境和样本计数见 `execution.md`。产品证据填写 `evidence-template.json`，覆盖分层见 `coverage.md`，F项阶段责任见 `findings.md`。

当前未执行Android构建、设备/声学、真实供应商、真实存储删除或真实儿童测试。没有运行60分钟和实际等待7天。删除双件把全部副本放在内存集合中，不证明平台硬删除；管理双件将后台/锁屏/撤权限/识别失败抽象为同一释放操作，没有实现Android生命周期、持久限次或卸载归属恢复。后续必须接产品适配器和独立复核。

D05账号条件、D04设备归属与恢复、D02/D06全副本删除及D03声学观测保持门槛。真实服务、保护管理写入、真实问题材料、声学达标和发布均未放行。未修改V1配置、不部署、不采购、不触发Backlog、不自动合并。

R94原报告与复现附件原文归档于`docs/reviews/review-tita-94.md`和`docs/reviews/tita-94/`；归档probe.py依赖旧接口，不执行它以免旧mock失效触发设备命令。新复现由`r94_check.py`全量拦截设备查询；结果见`r94-controls.json`，修正请求待独立复核，不自行关闭。
