# TITA-94 独立工具审定

日期：2026-11-24。审定人为构建交付成员，非M02作者。对象为PR #32，远端head经git ls-remote及GitHub PR读取一致：`0db95458ac6e0240c669207eb53a49b0ed11012e`；base分支`agent/agent/f3ceec854fea`，base提交`c9270fb2fab75a1efd7809f9913dc51d9d02bdbb`，与M01 PR #31一致。差异15个新增文件1075行，仅测试工具及文档，没有产品代码或V1配置改动。

结论：**工具夹具用途有条件通过；不能作为产品自动验收门。可由协调方安排一次串行D03只读设施盘点，但原始音频设施清单须本地脱敏后才上传。M03可推进隔离的协议与确定性状态机实现；产品PASS、声学达标、真实服务及受保护功能仍不放行。** 本项审查交付完整，无需产品确认；没有派单或操作手机。

## 实测证据

仓库根目录执行（输出位于仓库外的本任务工作目录，随本报告附件交付）：

```sh
python3 -m tools.v2_harness.run --out ../review-evidence/self-test-independent.json
PYTHONPATH=. python3 ../review-evidence/probe.py
```

19个自测方法全部通过，失败/异常/跳过均0。独立子进程负控中，错误未静音、异常失效、缺失和空观测适配器分别退出1。缺适配器、仅夹具scope、0样本、缺必要声学观测分别拒绝。检查过全部工具代码、dialogues.json、覆盖映射、执行记录、原自测及F项登记，亦对照M01技术契约和TITA-93原评审。

独立复跑的provenance为本次head、dirty=false；全部8个工具/输入SHA-256与作者报告相同。作者报告HEAD为父提交且dirty=true，不能将其归为父提交测试；逐文件哈希确实对应PR最终工具内容。在独立临时git仓库复制工具，先clean，再只给dialogues.json追加换行，验证同HEAD下dirty由false变true、该文件哈希变化且等于实际字节SHA-256。未修改作者仓库文件；最终git status为空。

盘点所有外部调用均通过mock拦截，未调用真实ADB或system_profiler。验证Mac分支恰好6条命令，每条10秒超时、capture_output=True、不启shell；非零返回、缺二进制、超时均输出unknown，不回显stderr。显式serial不出现在模拟报告。mock不能证明设备可达或Mac采集成功。

## 发现与修正要求

**R94-01：证据结构校验尚不足以承担产品验收门（中等，产品PASS接入前必须修复）。** `tools/v2_harness/evidence.py:23–30`，独立probe记录了以下被接受的PASS结构：缺失timeouts、attempts=float('nan')、attempts=True、requires_acoustic=0且无声学观测。NaN不满足“<=0”，bool及0/1又与整数/布尔值相等。它们不满足明确完整的计数/分类契约。现有19项测试未覆盖这些输入，故工具自测绿不代表此门已闭合。

修正要求：attempts为严格正整数（拒bool、非有限数和其他类型），failures/errors/timeouts等计数显式必填且为非负整数；声学分类用严格bool并由受控场景定义决定，不能依赖报告作者自由豁免。接入产品时校验版本/来源/证据结构并关联实际执行与独立oracle；现有字符串存在性检查不能证明来源真实性。添加上述负控，补空dict/list观测的场景schema负控；`execute`目前只拒None，其余由oracle负责，禁止无条件True的oracle。本次没有据此虚构任何产品PASS，也未改作者代码。

**R94-02：盘点原始输出没有自动脱敏（操作约束，自动上传前需修正）。** `tools/v2_harness/inventory.py:15,31,35`会原样嵌入system_profiler输出，mock注入`SYNTHETIC_PRIVATE_DEVICE_NAME`后报告确实包含该字符串。README已明确上传前人工脱敏，故在有代理本地审查的流程下可受控执行；不能将脚本当作可自动上传的脱敏工具。建议改为设备匿名编号、输入/输出能力及采样设施等必要白名单，去掉个性化名称/UID/序列号/网络地址。缺省输出大小未设限、空stdout且退出0仍标observed也是已知限制；空值须由执行代理视为无有效证据，不据此判断设施可用。

## D03允许范围及前置条件

审定文件：`tools/v2_harness/inventory.py`，SHA-256：
`4212795f83c21b460ba4d7afb50ffc6dbc03948614cc9f5dc78fa3d100262747`。

允许命令穷举：

|命令|用途/限制|
|---|---|
|`adb -s SERIAL get-state`|目标连接状态，不枚举其他设备|
|`adb -s SERIAL shell getprop ro.product.model`|机型|
|`adb -s SERIAL shell getprop ro.build.version.release`|Android版本|
|`adb -s SERIAL shell getprop ro.build.version.sdk`|SDK|
|`adb -s SERIAL shell getprop ro.build.id`|构建标识|
|`system_profiler SPAudioDataType -json`|仅Mac主机音频设施；本地原始输出，上传须白名单脱敏|

前置条件：协调方独占串行手机时段；已知且确认目标serial；已存在ADB授权和工具、Mac可用python3（3.10+）；校验上述文件哈希和可信PATH二进制。不要将真实serial或原始清单贴到议题。ADB如未运行可能自动启动主机ADB server，因此要求既有可用连接，不能据文档“无服务启动”推断完全无主机副作用。未授权/离线/二进制缺失保持unknown，不为盘点改授权、配对或要求用户点按。

所有命令顺序执行，Mac最多6次调用，每次10秒，约60秒子进程超时预算（非整进程硬时限）；Linux只5次ADB，host_audio保持unknown。成功退出也不代表完整盘点成功，须逐字段核对。无安装/卸载/清数据、启动APK、权限/音量/路由/锁屏写入、录环境音、读取私人文件或killall。失败不自动扩大命令范围。

**可执行结论：满足前置条件时，可运行一次脚本，仅取得只读基础清单并本地审查脱敏；不可无人审查原样上传。** 本审定不额外批准dumpsys全量、包清单、锁屏/安全凭据或私人目录查询。脚本不测授权/解锁操作性、AEC、可编程外放、独立手机输出观测、共同时间误差或V1签名安装策略，均应保留NOT_VERIFIED。一次基础盘点无法关闭D03；缺设施就如实报告，不转交用户过程测试。

## M03边界与阶段门槛

允许建议：在隔离环境实现连接/会话/轮次/输出/任务/序列身份验证，取消先撤销代际与静音，再释放旧句柄，有界队列和不可重置重试预算；实现已播公共事实与秘密分离、部分段不确认、播放实例/流代际与采样坐标绑定。把现有双件当反例输入，另建独立oracle和实际协议适配器；加入断线重连、旧安全/图片回调、图片ready与旧ACK交叉等集成断言。协议fixture不覆盖完整序列化、安全schema、摘要/隐私状态或产品资源所有权，不能直接当生产实现。

F03在M03/M04闭合前，不能提交不可靠已播事实或据此揭图；ACK不是外部可闻证明。M03可以先做纯本地协议与合成适配，真实供应商调用仍须D05，音频端到端及P11–P13须D03。证据门产品接入须先修R94-01。F01/F02继续由M08关闭，F04/F05由M09关闭；真实管理保护写入须D04、真实问题材料须D02/D06，原F01–F05全部OPEN。

38行是映射，完整产品A执行器和真实适配器均0。10条自造文本仅场景输入，一秒16kHz工程音调不是合成语音、童声、ASR或自然度测试。本次产品A01–A38全部NOT_RUN、样本0；真实声学、普通回复/插话各100次、60分钟混合、实际7天、真实副本删除、供应商账单及儿童泛化全部未测。无重型构建、APK、部署、收费、合并或V1修改。本报告及复现附件就是本项交付，没有仓库改动或新PR。
