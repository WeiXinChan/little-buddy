## 结论与对象

**M05不通过，保留两项必须修正的软件发现；不冻结M06无关本地功能。**

审查 PR https://github.com/WeiXinChan/little-buddy/pull/35 ，首次及交付前远端 refs/pull/35/head 均为 `059ef654ea50c3a0cef928150016db348a628e6c`。作者已完成，未修改作者代码、测试断言，未占手机、合并、部署或开通服务。需求按批准V2、5–8岁，依据R08/A10/A12/A33及父任务最新补充。TITA-83所有原始提醒线程和交付附录已读，TITA-97复核附件已下载比较。

## 必须修正

### R99-01（高）：旧ASR在新Session读取上下文并继续调用上游

位置：`backend/v2/voice.py:256–290`，handoff分支位于同文件约340行。

`PYTHONPATH=little-buddy python3 probe99.py` 使用真实VoicePeer.respond的handoff分支：旧ASR已进入finish；旧会话已有偏好；明确handoff关闭旧Session并新建Session；旧ASR吞cancel继续等待；新Session进入private_mode并加入纯合成私事；释放旧ASR。epoch/revision仍未切换，此调度有意在客户端下一次stop之前完成。

实测 `handoff_cancel_swallowed=true`，`stale_asr_dispatched_with_new_context=true`：旧文本“旧参与者合成私事”与新人私事上下文一起传给endpoint。身份判断在endpoint返回后才执行，太晚阻止跨参与者的上游派发。

**边界**：实测 `stale_analysis_rejected=true`，旧ASR没有污染新analysis；已经在运行的端点模型吞取消后也被阻止回写。不能把本发现写成“已证明analysis污染”。将Session条件仅在内存移除的错误实现负控，会让两项analysis隔离断言均失败；生产文件未更改。负控结果见 `probe99-negative.json`。

建议在异步任务创建时绑定产生时Session对象/身份，并在每次异步返回及下一次上游派发前校验；只使用该身份授权的上下文快照。取消、pending探针、finally回写和释放也应同样绑定身份。先使旧任务不可再派发，不能依赖供应商配合cancel。补同epoch/revision下ASR与endpoint吞取消的配对测试，验证不仅无本地写入，而且没有越界上游请求。

### R99-02（中）：不同维度的有效偏好因单类4槽过早淘汰

位置：`backend/v2/session.py:343–353`。

同一生产VoicePeer依次输入“我喜欢猫／蓝色／面条／足球／下棋”，均保留完整来源、未撤回、未纠正。四个维度时猫仍在facts；第五个维度把动物偏好挤出固定3历史+当前槽。再走10轮普通背景，让recent淘汰后，完整context不再有猫。实测总记忆只有 **1682 bytes**，没有容量压力，未产生产品failure。

该反例针对仍相关的不同维度事实，不要求无限保存所有历史；当前实现按粗粒度preference而非语义纠正/维度淘汰，不能以此证明多维偏好保留。建议在有界容量内保留互不替代的当前来源，明确同维度纠正与可淘汰历史；无法安全保留则原子拒绝，不能无声把仍相关事实当旧背景丢弃。补4维通过/第5维失败配对及窗口淘汰后追问。

## 独立验证及证据边界

|项目|结果|含义|
|---|---|---|
|Python模块|59/59，无跳过|包括作者真实VoicePeer长聊回归的非作者复跑；固定模型/PCM|
|工具自测|28/28|工具证据，不是28项产品验收|
|JVM|68总项，66通过、2既有V1跳过、0失败/错误|持全局锁串行一次离线构建执行|
|R97-04原独立测试|原附件与仓库字节一致；3/3通过|solo预算软件子范围可关闭；不是设备无回包证明|
|新增独立检查|16/16|六维错误ACK无副作用、正常ACK对照、旧摘要/图片、原会话清空、原子容量、角色交换、长聊|
|新增长聊|140轮；累计输入120010B、输出75600B；142个音频段；末尾16条已播记录；无failure|生产VoicePeer、固定计划和合成PCM；不是实云长期语义/60分钟/声学|
|ASR/endpoint负控|2/2隔离差异检出|移除身份检查后两个analysis断言失败；生产检查通过|
|源码/制品|25份源码+2个APK哈希27/27一致；两APK验签成功且证书一致|下载了本次新包，未安装；未以旧包SHA代替|

主APK SHA256 `866f3f3e534d2557f9ab7aacc0ce1d41368f76d751d997d01a7deb945ac39440`；测试APK `e5f11334b9f1bb73159e869eca8565b702eff02f1e2418c6f989e98163f6ebd5`。包名沿用工程隔离版本，以SHA区分，不当正式发布包。原始作者代码提交与远端交付SHA不同，作者bundle与清单保留；本次核的是远端head的25份受测源码和实际下载APK。

独立检查驱动初期有两次设施错误：未提供compact能力，以及合成输出超过CompanionPolicy单句240字限制。原始14/16结果与驱动保留，不能归产品缺陷。补齐接口并使用合法180字短句后16/16；未修改生产边界、代码或断言。`checks99*.json`中累计输出是计划文本量；仅最终成功轮才能当已播输出量，失败驱动的计划量不可当已播证据。

## 真实模型：保留所有轮次，不把oracle失败当错答

仅使用既有已核北京配置、qwen3.8-flash别名和合法合成内容；未更换账户、充值或保存密钥/录音。三轮各5项操作，HTTP调用分别19/13/19，共 **51**；HTTP失败均0。模型是配置别名，供应商不可变版本快照未知。

原始脚本结果分别 **3/5、4/5、5/5**，各自JSON保留，不能合并成产品通过率。每轮含三项来源异措辞、正常虚构安全、两轮真实VoicePeer私事转共享；私事项耗时是两轮合计，不是单轮首回复或声学首声。没有用429当额度，无新增429调用；原403/429/网络/超时六类确定性反例在59项回归中通过。

否定偏好原oracle要求连续子串，存在误报。`oracle-audit.json`用三条正确重排措辞证明原oracle会拒绝；前两轮未留最小回复，markers不能证明语义错误，故两项记为 **oracle不充分、产品结论不确定**，不列新产品缺陷、不事后改绿。第三轮增加最小合成回复摘录，直接读到“你喜欢狗，不喜欢猫哦”，语义正确；主语和时间案例也保留对应摘录，正确。未修改生产日志策略。

私事转共享：首轮综合布尔false，未记录细分flags，原因无法回溯；可能涉及模型入口/退出/投影/软件failure任一项，**不能据此宣称泄漏**。第二、三轮均 entered_private/exited_private/secret_absent/no_failure 四项true；后两轮不能覆盖首轮失败，也不能证明稳定泛化。正常虚构安全三轮均通过。以上是15项小样本操作，另保留作者原19/19及所有历史失败，彼此不混算。

## 交付门槛与M06建议

可先行M06本地图片调度、占位、话题代际和取消、过期/隐藏谜底门控及合成故障检查；建议采用不可复活Session身份，不沿用仅epoch判断。R99-01必须在跨人集成/上游并发复用前修正；R99-02须在宣称多维偏好和A12记忆完成前修正。不因设备安装或声学缺口冻结这些本地功能，不派新成员。

F03/A12/solo-A18整体仍OPEN。真实VoiceClient黑洞instrumentation已构建，本轮设备/安装/声学 **0次**；R97-04仅关闭本地预算软件子范围。设备后续以127.0.0.1和既有原IP SAN证书核验链及主机名，分别诊断push与pm；不关闭TLS、不要求用户过程点按/录音/试听。供应商账户留存/删除条件、真实账单、不可变模型版本、儿童效果与完整实云长时性能未核实。

## 复现

从工作目录布局执行（little-buddy为上述head的干净检出）：

```bash
PYTHONPATH=little-buddy python3 probe99.py
PYTHONPATH=little-buddy python3 probe99.py --negative-control
PYTHONPATH=little-buddy python3 checks99.py
cd little-buddy
python3 -m unittest discover -s tests/v2 -q
python3 -m unittest discover -s tools/v2_harness/tests -q
# 沿用既有SDK；全局锁和离线缓存，不下载新工具
scripts/with-build-lock ./gradlew --no-daemon --offline --max-workers=1 -Pv2Test :app:testV2DebugUnitTest
```

真实探针 `probe99_live.py` 只从systemd已授权EnvironmentFile/LoadCredential取既有配置；不直接打印环境。附件保存各轮计数、原判据结果、第三轮最小合成摘录、源码与制品哈希、日志、R97-04 XML及探针清单。无仓库变更，因此以任务附件交付独立评审，不创建空PR。任务交付in_review，不自动done。
