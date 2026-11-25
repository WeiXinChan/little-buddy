# R87-01：系统到期清理草稿日志副本

旧 PR39 head `34b97d44a736de303f2b015d48ed18866986b9a2` / tree `36da2aa368bbe61d60861a182d2c716aa25ab270` 的独立 QA 结论为正常 41 项、40 通过/1 失败/0 跳过。此真实失败不由作者原 34 项通过或 5 项突变检测通过覆盖。

修复只在 FeedbackCore.sweep 加入活跃草稿的清理：可信时间达到所选最早源条目的原 7 天截止时，原 ByteArray 逐字节清零，草稿换为空缓冲，预览范围/条数/字节归零，revision 推进且 confirmation 清空。系统路径不调用需要 PIN 的 withoutLogs，不依赖用户重开、再次 preview 或提交。包含新旧日志的范围采用既有保守策略整批清空，新的源日志仍保留；说明和其他未到期问题不受影响。

单个核心仍只支持一个活跃草稿；多草稿验证覆盖同一实例的多次替换/取消，以及两个独立实例的活跃草稿逐一 sweep，不引入共享库多写者能力。测试持有原 ByteArray 引用检查清零，避免仅检查换成空数组而旧副本仍有内容。

## 原始证据与不变断言

- `original-qa-evidence.zip` 是认证 CLI 下载的原 QA 压缩包，未经重写，含原 41 项结果、旧失败日志、原探针与 Android jar 摘要。
- `Review39Probe.kt` 与包内 `qa39-probe.kt` 字节完全一致，7 项独立检查和原失败断言均原样保留到测试源集。
- `old-head-failure.json/log` 是作者在本隔离树用 git show 读取固定旧 head 产品源码、执行该原方法的新复现：编译成功，正常测试分母 1、失败 1、跳过 0，进程退出 1。它不是预期突变负控。

```bash
scripts/with-build-lock python3 scripts/test-m09-core.py \
  --source-ref 34b97d44a736de303f2b015d48ed18866986b9a2 \
  --case Review39Probe#expiredSelectedDraftCopyMustBeReleasedBySweep \
  --android-jar /home/ubuntu/.gradle/caches/8.13/transforms/9ec1aa52f1567b6bf359cfb66d138a5b/transformed/android.jar \
  --out build/m09-core/r87-old-failure.json
```

## 修复后复现命令

```bash
scripts/with-build-lock python3 scripts/test-m09-core.py \
  --android-jar /home/ubuntu/.gradle/caches/8.13/transforms/9ec1aa52f1567b6bf359cfb66d138a5b/transformed/android.jar \
  --out build/m09-core/r87-fixed-baseline.json
scripts/with-build-lock python3 scripts/test-m09-core.py --negative-controls \
  --android-jar /home/ubuntu/.gradle/caches/8.13/transforms/9ec1aa52f1567b6bf359cfb66d138a5b/transformed/android.jar \
  --out build/m09-core/r87-fixed-negative.json
```

缓存 jar 路径为本机编译输入，可用同摘要 jar 替换；无需手机、模拟器、网络或 Gradle 参数扫描。全部构建串行经既有 heavy.lock，编译 768MiB/运行 256MiB；原授权、IO 和持久事务产品代码不变。

新增 9 项覆盖到期前 1ms/等于/之后、撤销权限、production deny 授权端口、未再次 preview 时确认失效、重复清理幂等、部分过期范围、替换/取消草稿、两个独立活跃草稿、说明与未到期问题隔离。原 7 项独立检查继续含 300ms 内撤销/无耐久材料/重启 outbox、最终 provider admission 和合法事务持久结果。

Android 工厂与全部产品核心以现有 Android jar 一同编译；此证据不等于 APK 或真机 Keystore 运行。完整 M09、A24–A31、D02/D06、全副本删除及 UI/后台接线继续 OPEN，生产默认拒绝不变；原 QA 独立复核，root 审合。

## 本轮实测结果

| 执行 | 实际分母 | 通过/检测有效 | 失败 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| 固定旧 head + QA 原方法（非突变） | 1 | 0 | 1 | 0 |
| 修复后正常回归（原作者34 + 原QA7 + 新增9） | 50 | 50 | 0 | 0 |
| 修复后突变负控（原5 + 移除草稿清理1） | 6 | 6个有效 | 6个预期断言失败 | 0 |

所有变体实际编译成功，六个负控日志分别命中较早截止、缺账本恢复、submit/clear旧许可、部分删除和原 R87-01 断言；负控整体退出0。原34项及QA新增7项不改断言复跑，阻塞IO期间300ms撤销/重启outbox保护保持通过。含Android工厂编译通过，未执行Android运行或APK构建。Python语法和提交前空白检查通过。固定源码逐文件SHA256在各JSON中，交付前已重新核对。
