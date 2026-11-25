# M08 家长权限域：独立核心交付

固定基线 `112e456ff09f619ab5929b486ed73358110ba3d5`。此 PR 仅新增
`v2/parent`、对应测试及离线验证脚本，不修改 V1、M06、Activity、manifest、CI
或生产配置。没有 APK、安装、部署或产品验收通过声明。

## 已实现边界

- 六位 ASCII 数字 PIN，保留前导零；每次尝试清除传入字符数组。每设备随机
  16 字节盐、600000 轮 PBKDF2-HMAC-SHA256、32 字节派生值、常量时间比较。
- Grant 是进程内引用能力，不实现序列化；验证域实例、generation、pageEpoch
  与单调时钟闲置期限。120000ms 边界拒绝，只有有效本地管理操作续期。
- `enterPage()` 撤销旧代际；宿主必须在 HOME/onPause、失焦、锁屏、页面重建、
  取消和退出调用 `revoke()`。进程重启不恢复 Grant。本 PR 尚未接宿主生命周期。
- 每次验证先原子预留失败，再执行慢哈希。第五次失败起每五次为一组，冷却从
  60s 翻倍至 1h，只有正确 PIN 且成功持久化才清计数。每次进程重建重新执行
  记录的完整冷却期，保守延长，不使用墙钟；force-stop/重启不能缩短冷却。
- 初始化/重置使用新鲜、限设备/动作/期限、一次性 OwnerChallenge；迟到回调
  在提交前重验代际。生产工厂始终使用拒绝提供者，三项 capability 明确为
  UNCONFIGURED：首次归属、系统验证恢复、生产端点发行。测试提供者仅合成证据。
- 本地音量上限仓库需要有效 Grant；异步准备完成后只能调用最终仓库方法，
  不能缓存先前鉴权结论。落盘及发布前重验。普通 PIN 无部署凭据发行能力。
- Android 使用独立 Keystore AES-256-GCM alias，随机 12 字节 IV，AAD 绑定
  域/schema/device binding；完整记录包含哈希参数、盐、验证值、计数和配置。
  AtomicFile 位于 noBackupFilesDir，缺文件但已有 key、损坏、解密失败和写失败
  都隔离，不当成首次安装。解密缓冲与派生缓冲尽力清零，不承诺 JVM 绝对擦除。
- 存储与慢哈希必须离主线程。生产单例工厂保证单进程一个授权域；调用者应使用
  一个串行 worker。最终授权检查与文件提交互斥，撤销在线性化顺序中发生在提交前
  则拒绝，发生在提交后则该操作已提交。不隐式排队重试，不写秘密日志。

## 接口与剩余交付（OPEN）

`AndroidParentDomain.open(context, trustedDeviceBinding)` 必须在 worker 调用。
binding 必须来自未来受审的归属提供者，不能新生成一个 ID 就接管既有配对。
当前没有真实提供者，故实际用户无法初始化，符合默认拒绝的独立核心范围。
未来提供者须核验注册发行方、设备绑定、动作、有效期、撤销及重放，系统解锁
不能单独证明家长归属。生产工厂没有测试注入或 Intent extra 赋权入口。

UI、FLAG_SECURE/输入保护、Android 生命周期实际接线、M06 停播/停止上传/原生
watermark 管理边界、可信部署端点和设备 token 发行、真实系统恢复均未接通。
本 PR 不提供端点输入表单，不读取/删除配对。恢复仅更新 PIN 记录并保留本域
配置；跨重装归属、配对及凭据保持仍依赖真实提供者和后续集成。

M06 预期接口：`enter(epoch)` 先停止儿童上传、撤销输出及 decoder/buffer，成功
completion 后才显示管理页；失败隔离；`leave(epoch)` 只回待唤醒。该接口只是
交接契约，必须与 M06 冻结签名协调后再实现，未复制 PR36，也未声称音频零上传。

本地保护不抵御 root 整体数据回滚、卸载或清除数据/Keystore；未证明硬件抗穷举。
只使用单进程，不支持多个进程并发访问此存储。读后校验可发现可观测提交故障，
不能以 JVM 测试替代真实 Android fsync、掉电、Keystore 失效和 AtomicFile 恢复。
磁盘故障一律隔离，可能需要后续受审恢复流程；不能删除数据绕过。

## 作者验证证据（2026-11-25）

在现有管理员全局锁 `/var/lock/little-buddy/heavy.lock` 下串行运行：

```sh
scripts/with-build-lock python3 scripts/v2-parent-tests.py
# Android 适配编译同时验证：使用本机缓存的 Android API jar
scripts/with-build-lock env PARENT_ANDROID_JAR=/path/to/android.jar python3 scripts/v2-parent-tests.py
```

首轮 20/20 JVM 测试；补充生产 AES-GCM 封装与故障反例后 24/24 通过，退出码 0，
JUnit 用时 54.271s。第二轮同时编译所有新增 Kotlin（含 Android 适配），使用已有
Gradle 缓存的 Kotlin 2.2.21/JUnit 4.13.2 与 Android API jar；无依赖下载、Gradle
构建、模拟器、手机操作或外部 CI 等待。最终仅新增 capability 标记后另作适配编译。

反例覆盖：错 PIN/非 ASCII/伪造授权、跨域跨页、HOME 等价撤销、超时迟到写、
进程重建、跨重启限次/指数封顶、预留和成功提交故障、配置落盘故障、损坏/截断/
未知版本、AES-GCM 篡改 IV/密文/绑定/密钥、nonce 重放/过期/动作错误及默认拒绝。
实际 Android KeyStore、AtomicFile 故障/掉电、系统认证、发布 manifest、UI 与音频
集成、OPPO 及儿童语音均未测。没有 Android instrumentation 或 APK 通过证据。

600000 轮 KDF 在 Linux 主机串行 worker 四次样本：573、590、587、586ms。
这是候选参数的主机数据，未预热控制/统计显著性/目标机 p95，不能认定 OPPO 达标。
后续目标机测量后审定参数，不得因性能问题静默降级。测试只打印轮数/耗时，不打印
PIN、盐、派生值、密钥、凭据或音频。A27/A28/A34、D04 保持 OPEN，等待独立复核。

## R86-01 修复与针对性验证（2026-11-25）

QA 对旧 head `84129d6` 的静态审查指出：Android 每次写入都允许 `key(true)`，
已打开的域运行中若 key 缺失，会尝试生成新 key 并覆盖记录。这是确认的代码分支
问题，旧版 24 项 JVM 测试未覆盖该分支；不是 Android/OPPO 故障实测。

本次 Android 适配委托给可注入 key/file 提供者的生产 `SealedParentStore`。
只有 read 同时确认无记录且无 alias 才进入 FRESH；第一次可信初始化写入在尝试
生成 key 前就消耗该资格。后续写入只取 existing key，缺失/失效立即隔离，不生成、
不提交文件。读取和提交的既有密文作为连续性证据，换成另一把 key 也不能覆盖记录。
生成后首次落盘失败永久隔离当前存储实例；重启时有 key 无记录同样隔离，不自动重试。
生产首写仍必须先经过 ParentDomain 的真实归属证明，当前提供者未配置故默认拒绝。

同时将 verify/replacePin 的 worker 检查移入 PIN 清理的 try/finally，检查抛错也清零
调用者输入缓冲。不扩大 UI/音频改造；主线程 revoke 与完整磁盘 IO 共用锁、可能等待
慢 IO 的宿主接线风险继续 OPEN，需未来宿主串行策略和设备延迟实证。

本轮在同一管理员 heavy.lock 下串行执行：

```sh
scripts/with-build-lock env PARENT_ANDROID_JAR=/path/to/android.jar python3 scripts/v2-parent-tests.py
# 只复跑 R86-01 和输入清理的 11 项针对性用例：
scripts/with-build-lock python3 scripts/v2-parent-tests.py --r86-only
# 临时副本故意恢复“缺 key 时生成”，两项运行中丢 key 反例必须失败：
scripts/with-build-lock env PARENT_ANDROID_JAR=/path/to/android.jar python3 scripts/v2-parent-tests.py --r86-key-loss-negative-control
```

实际全量结果 **35/35，失败0、跳过0，56.922s，退出码0**：原24项及新增11项；
所有 Kotlin 含 Android 适配同时编译通过。新增11项覆盖：既有记录缺key启动拒绝；
open 后丢key再 verify/save 均拒绝且生成/覆盖为0；失效key与替换key拒绝；首次可信
初始化只生成一次；无归属提供者不生成；首次生成后落盘失败及重启隔离；鉴权拒绝不
生成；verify/replacePin 的 worker 检查抛错也清 PIN。用真实 JVM AES-GCM 和生产
存储状态机，key-provider/file 为可计数合成端口，不是 Android KeyStore/AtomicFile。
本轮主机KDF样本593/585/609/588ms，OPPO未测。临时副本负控实际运行11项，
9项通过、运行中丢key后的 verify/save 两项按预期失败（4.402s）；JUnit退出码1，
脚本核验失败数量后退出码0。负控不修改产品源码，不计入35项正向回归的通过分母。

测试未占手机、未开模拟器/HDA、未运行 Gradle 或等待外部 CI；真实 Android 密钥
删除/失效、AtomicFile 故障、生命周期及全部既有集成缺口仍未测，A27/A28/A34、D04
保持 OPEN。新 head 待非作者复核受影响范围、root 审合。
