# M09 作者验证记录

2026-11-25；固定 base `112e456ff09f619ab5929b486ed73358110ba3d5`。最终 head/tree 以 PR 与任务交付评论为准，证据 JSON 中源文件 SHA256 已在交付前逐项与工作树核对。

| 实际执行 | 分母 | 失败 | 跳过 | 结论 |
| --- | ---: | ---: | ---: | --- |
| `scripts/with-build-lock python3 scripts/test-m09-core.py --out build/m09-core/baseline.json` | 34 | 0 | 0 | 实际 main Kotlin 核心 + JUnit，真实文件/AES-GCM，合成时钟/授权/网络端口 |
| `scripts/with-build-lock python3 scripts/test-m09-core.py --negative-controls --out build/m09-core/negative-controls.json` | 5 个变体、各 1 个指定测试 | 5 个预期断言失败 | 0 | 5/5 检测有效；每个变体先编译成功，负控命令整体退出 0 |
| Python AST 语法检查 | 1 | 0 | 0 | 无需网络 |
| `git diff --cached --check` | 1 | 0 | 0 | 提交前空白检查 |

负控不能混入正常测试通过分母：

- 把较早截止改为较晚：预期 `172801000`，实际 `604801000`，测试失败。
- 缺删除账本时直接读旧材料：期望 QUARANTINED，实际未拒绝，测试失败。
- 把最终许可改成 staging IO 前取得的旧布尔：submit 与 clear 两个独立阻塞反例分别期望 DENIED，变体均未拒绝，两个测试失败。
- 部分副本回执一律已删除：期望 DELETING，实际 DELETED，测试失败。

阻塞授权正例同时校验持久密文字节未变，释放后恢复新管理代际、重启再检查源日志保留/无 outbox；非仅检查网络 spy。另测合法提交决定之后撤销，特定事务仍按真实完成结果显示。

开发中曾出现两次测试设施失败，均已修正后重新执行最终 34 项：第一次 JUnit 初始化失败（一个表达式体测试返回 String 而非 Unit，执行分母 1，失败 1）；第二次当时 33 项中 1 项失败（撤销后测试自身没有重新建立管理代际便尝试 list，正确获得 DENIED）。一次重构建锁占用返回 75，未启动编译；保持共享原锁，无并发构建。以上不伪装产品缺陷或最终通过记录。

未执行：AndroidFeedbackVault 的 Android 编译/Keystore 实测、APK 构建、设备/生命周期、真实平台业务、全副本删除、实际等待七天/一天、儿童效果、A24–A31 产品集成。当前隔离树没有配置 Android SDK，直接缓存编译器路径用于验证独立核心；不借诊断树或启动模拟器。此 PR 没有解除上述验收项。

后续按冻结顺序由原 QA `ce2bcefb` 独立复核，root 审合；作者未另行派 QA、未合并。合成 provider/authorizer 只在 test，生产默认拒绝/UNAVAILABLE。
