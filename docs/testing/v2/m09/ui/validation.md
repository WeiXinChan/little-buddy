# M09 UI / Linux 验证记录

固定 base `77893453fa855eb31838ce506fa36b6debe9a696`，分支 `agent/tita-87-feedback-ui`。本目录 JSON 记录最终生产/测试源 SHA-256，原始 stdout 随日志保留。所有编译经 `scripts/with-build-lock`，全局 heavy.lock=1，无并发重构建。

| 验证 | 实际结果 | 边界 |
|---|---|---|
| Android API jar + Kotlin 编译、正常 JUnit | 67执行 / 67通过 / 0失败 / 0跳过 | 原50项 + 新17项；真实域/文件/AES-GCM，合成时钟/Provider/测试认证 |
| 突变负控 | 9个均独立编译成功，9个各执行1断言并预期失败，0跳过 | 不计入67正常通过数 |
| Gradle :app:compileV2DebugKotlin --offline --no-daemon --max-workers=1 | 失败，exit1，SDK location not found，17s | 本工作区无完整Android SDK；没有APK/设备运行证明 |
| 源码 diff --check（排除原始 .log） | 通过 | gradle.log 保留 Gradle 原始尾空白，完整 diff 检查因此报告该行 |

## 可复现命令

Android API jar 已有缓存路径按环境传入；本次 SHA-256 为 `7123df2cceaebc66f3991a480964968c9d9603f6abd542ea8878c39db70fcb07`。

```sh
scripts/with-build-lock python3 scripts/test-m09-core.py --android-jar "$ANDROID_API_JAR" --out build/m09-core/ui-baseline.json
scripts/with-build-lock python3 scripts/test-m09-core.py --negative-controls --out build/m09-core/ui-negative.json
scripts/with-build-lock ./gradlew :app:compileV2DebugKotlin --offline --no-daemon --max-workers=1
```

正常测试覆盖：Provider缺失拒绝；提交/列表/详情/回复/整单撤回控制器；本机副本清除保持原远端状态与截止、重开仍清除且迟到回复不复活；旧页关闭不伤新页；排队写入/迟到UI/迟到admit不可借新Grant；编辑使确认失效；系统sweep无需PIN；授权失效tick锁页擦草稿；过期预览被撤销；不同本地vault隔离；schema1迁移；真实ParentDomain/Grant的缺失gate、撤回与idle拒绝。测试用快捷PinHasher和合成Provider仅位于test。

9个负控分别移除/破坏：较早删除截止、耐久删除账本、阻塞IO后submit最终授权、阻塞IO后clear最终授权、全副本删除回执、过期草稿副本清零、旧任务页归属检查、迟到UI版本检查、gate必须执行decision。每个保留原断言，实际trace见negative.log。原PR39历史失败/QA复现与R87-01修复证据仍原样保留在上级目录，未用token过期代替副本擦除。

## 未测与限制

早期开发曾有65、66项通过；最终冻结以本目录67项报告为准。共享锁占用exit75及首次输出目录不存在没有执行测试，不计入分母。

API编译包含新增原生页面、AndroidFeedbackVault、JobService、父域源码，但不是Android运行或APK证明。Gradle完整构建失败原件见gradle.log，未以API编译掩盖。未测试真实Keystore/OS调度重启/Doze/页面渲染、平台删除、真实跨设备归属与可信时间；无Mac/手机/模拟器任务。M08 host采用已冻结v1端口、实际门禁与路由依赖后续合树装配，本轮只验证独立端口。完整M09/A24–A31及D02/D06继续OPEN，由原QA独立复核再root审合。
