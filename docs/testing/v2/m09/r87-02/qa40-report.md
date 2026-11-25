# TITA-87 / PR40 独立代码复核

结论：**建议暂不合入，R87-02为合入前修复项：成功到期清理后，已打开的详情页仍持有并显示过期说明。** 原67项和9个突变均独立复跑有效，但不能替代新增失败反例。交原519修复并由QA复核，root最终审合；本轮未改作者产品代码或合并。

## 固定对象、范围及实际装配

- PR：https://github.com/WeiXinChan/little-buddy/pull/40
- base：`77893453fa855eb31838ce506fa36b6debe9a696`
- head：`c0f3e38b853e3090c8c98e9d76cdcbc916a80101`
- tree：`d84aa1bc993e2288ae70c4b50dac4629c27cdc40`

独立detached QA树固定上述版本，17文件1257新增/11删除；生产差异限feedback域及共享main manifest的JobService/boot permission注册，不改parent/管理host/M06代码。注意manifest位于main源集，注册声明会随共享该源集的flavor一起打包；本轮未生成V1 APK或改变V1配置，不宣称已验证各variant最终合并manifest。与M08约定的工厂/gate/handle v1已读，独立端口与真实装配区分如下：

| 层次 | 实际代码 | 当前证据/限制 |
|---|---|---|
| 原生页面 | FeedbackPageFactory/AndroidFeedbackPage，列表、详情、编辑、范围预览、确认、撤回、本地副本及源日志清理 | Android API编译成功，未渲染/点按执行；测试名含native也仍是控制器JUnit |
| 页面授权 | ParentFeedbackAuthorizer持真实ParentDomain/Grant类型，经FeedbackGrantGate决定 | 当前base没有acceptProtected扩展；测试gate是端口/缺失默认拒绝，不是实际生产授权接线 |
| 主入口 | 无Activity/管理host调用FeedbackPageFactory.create | 尚不能从当前主入口到达页面，已明确为后续依赖PR |
| 运行时 | 页面工厂首次创建时调用AndroidFeedbackRuntime.open，进程单实例/单worker；该入口亦用于JobService唤起 | 当前未装配页面时不会由管理主入口启动；不能宣称生产已开始周期清理 |
| 系统任务 | persisted JobScheduler、15分钟周期、BIND_JOB_SERVICE保护，重启后onStartJob调用open/sweep | 代码/API编译证据，非OS重启/Doze/断电下的执行实证；注册需open实际调用 |
| 平台 | 默认UnavailableFeedbackProvider，无真实工单端点/回复轮询 | 明确不可用，不发送，不把本地不同vault当真实设备绑定 |

经认证CLI下载本轮证据包，implementation/validation/route-contract及Gradle原件与仓库字节相同；freeze匹配，独立正常编译来源哈希与作者报告一致。读取关联表时自动完成禁用，PR40 open/未合；外部CI为1通过/1pending，未等待或重跑，pending不计通过。

## 独立实测分母

| 执行 | 尝试 | 通过/检测有效 | 失败 | 跳过 |
|---|---:|---:|---:|---:|
| 新head原正常JUnit | 67 | 67 | 0 | 0 |
| 新增到期详情独立反例 | 1 | 0 | 1 | 0 |
| 正常合计 | 68 | 67 | 1 | 0 |
| 9个突变，各编译后执行指定方法 | 9 | 9检测有效 | 9个预期断言失败 | 0 |

67项=已审核心50+新流程17，不按子断言/分支膨胀分母。正常及独立反例编译包含真实feedback/parent生产源码、Android页面/工厂/JobService，使用缓存Android API jar；正常JUnit退出0，新增JUnit退出1。突变命令退出0仅表示9个检测有效，子进程均实际退出1、断言失败1项，不混入正常通过分母。

实际命令：

```sh
# m09-ui-qa 工作树
scripts/with-build-lock python3 scripts/test-m09-core.py \
  --android-jar /home/ubuntu/.gradle/caches/8.13/transforms/9ec1aa52f1567b6bf359cfb66d138a5b/transformed/android.jar \
  --out ../qa40-baseline.json
scripts/with-build-lock python3 scripts/test-m09-core.py --negative-controls --out ../qa40-negative.json
scripts/with-build-lock ./gradlew :app:compileV2DebugKotlin --offline --no-daemon --max-workers=1
# 工作树上一级，独立探针编译及JUnit
m09-ui-qa/scripts/with-build-lock python3 qa40-run-probe.py
```

所有重型任务复用heavy.lock依次执行，编译-Xmx768m、JUnit-Xmx256m，无并发构建。未派Mac/手机、未启动模拟器/HDA，未收费/部署/改V1配置，无用户过程操作。

## R87-02：成功sweep没有清除当前详情的过期显示缓存

位置：`FeedbackEngine.kt:117`的afterSweep一开始`val previous = token ?: return`，仅处理预览确认；`detail()`在`:97`附近将token置null。`sweep():54`即使已成功删除材料，也不会为详情重建/清空屏幕。原生`FeedbackPageFactory.kt:97`分支将FeedbackView.description/reply写入TextView，若没有新render/pause，不会自行刷新。

独立可复现源码：附件`qa40-probe.kt`，方法`Review40Probe.systemSweepMustRetireDisplayedExpiredDetails`。步骤：

1. 合成Provider在真实文件/AES-GCM核心中提交自造说明，取得原单ID。
2. 可信合成时钟推进到原7天截止前1ms，使用**新的页面授权**打开详情，证明此时说明可读。不是把7天前的失效PIN当仍有效，也不以授权过期混淆材料到期。
3. 时钟推进1ms，执行产品FeedbackEngine.sweep，收到success=true。
4. 用同一真实vault/key重新构造核心，list为空，证明耐久材料已按期清理，不只检查内存spy。
5. 查看控制器最后发出的显示状态，仍是Detail且说明非null；预期不能继续显示过期说明，实际断言失败。JUnit实际1项/失败1/跳过0，0.281s，非预期突变负控。

这是当前控制器的可达过期显示缓存问题；原生TextView后果由渲染分支静态映射，未声称在设备屏幕复现或采集真实资料。详情在临近期限重新打开即可触发，后续刷新也不能依赖用户导航/再次preview。原单删除期限及缓存同删属于R13/R15/A25/A31，本轮“本地页面与系统tick集成”应覆盖，因此建议合入前修复。

建议最小方向：记录当前展示对象/模式，让每次成功系统tick在同一页面/展示epoch下重新检查详情及列表的有效性，材料已过期则撤掉敏感快照、原生文本和回调引用。保留旧任务/新页面隔离；后来的编辑不得被旧tick回调覆盖。不以重新PIN、无Provider或“存储已删”豁免显示缓存清理。补原单7天、较早撤回截止、已清本地副本、选定日志范围到期和迟到刷新竞争断言，保留本次失败原断言不改弱。

## 已通过范围及M10检查

生产页面明确Provider未配置/不可发送，确认发送按钮禁用，核心仍拒绝发送且不自动排队。纯说明默认无日志；范围选择经严格日期解析，预览有实际条数与字节，日志导出使用白名单结构化字段。说明/范围改变使旧确认失效，回复仅在家长页展示，无儿童语音/通知。原生view禁save state/autofill/个性化IME、窗口FLAG_SECURE；这些是源码/API证据，未做Android内存/IME实际运行验证。

原FlowTest及保留独立QA探针实际通过：旧任务不能借新页面授权；gate返回true但不执行decision不能发布事务；pause前排队任务拒绝、迟到UI不能恢复敏感预览；旧handle.close不撤新页。核心submit/clear阻塞staging期间revoke300ms内返回、释放后旧写DENIED、持久密文字节不变及重启outbox空的断言继续通过；合法决定后的写盘按实际事务结果完成，provider最终admit重新验权，不缓存早验布尔跨IO。

新增CLEAR_LOCAL沿用protectedChange，schema1迁移schema2，本地清理保留远端状态/原截止/幂等删除任务，迟到回复不再填回本地副本；不调用PIN/配对存储，也不清其他单和源日志。R87-01原数组清零/范围清除/确认失效、最早日志期限整批副本清理、无授权system sweep均继续通过。耐久撤回、重启重试、迟到撤回占优、较早删除期限、缺账本/损坏/中断发布恢复隔离原测试均通过。

M10当前证据：解密持久文件白名单哨兵检查通过，未知日志字段在落盘前被过滤；默认授权拒绝/缺gate/撤销/idle拒绝通过，两个独立vault不能互读清通过。后者只是本地存储隔离，没有真实设备凭据发行、服务器访问或跨设备鉴权证明。故不能将这些JUnit标成真实跨设备PASS。异常捕获显示有限错误类别，不输出原异常/家长正文到日志；OS崩溃/输入法/监控/SDK全链仍需后续检查。

9个突变逐一核实际trace：较早截止改晚；缺账本恢复拒绝移除；submit/clear早accepted布尔跨IO；部分副本误报DELETED；原草稿到期清零移除；旧worker借新页授权；迟到UI覆写Locked；gate不执行decision却返回true。均编译成功、预期断言失败，未用初始化/编译错误冒充检测有效。

## Linux构建与保留门槛

保留作者`gradle.log`未经改写。Linux评估：ANDROID_HOME/ANDROID_SDK_ROOT未设置，检查常用`/opt/android-sdk`、`/usr/lib/android-sdk`、`/usr/local/lib/android/sdk`、用户Android/Sdk及常见cache/local路径未发现完整SDK；对既有tech树按SDK文件名搜索也未找到可复用工具。存在缓存android.jar，只能用于上述Kotlin/API编译，不能构造成假SDK或据此宣称APK成功。本轮还独立执行同一Gradle离线命令：实际1次、exit1、12s，SDK location not found，原件`qa40-gradle.log`单附；无APK。

建议由协调/root提供既有合规Linux SDK路径或后续准备完整SDK36/build-tools和相关依赖，再在heavy.lock下执行标准Gradle。API编译不是AGP资源/manifest/dex/打包或设备KeyStore/JobScheduler运行证明。缺SDK是构建资源缺口，不替代R87-02代码修复，也不要求用户操作Mac。

完整M09/A24–A31、D02/D06、真实Provider全部副本/备份删除、归属初始化/恢复、设备绑定/可信时钟、OS重启/Doze调度、主入口/真实Grant装配及音频设备证据分别OPEN。整体双文件合法旧快照仍要恢复入口先隔离，不能宣称本轮已防任意回滚。root审合、自动done保持禁用。
