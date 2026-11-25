# M08 家长权限域：独立核心交付

固定基线 `112e456ff09f619ab5929b486ed73358110ba3d5`。此 PR 的功能范围为
`v2/parent`、对应测试及离线验证脚本。root 追加授权纳入下述两文件纯测试因果屏障
作为 CI 前置；不修改 V1/M06 生产代码、Activity 产品入口、manifest、workflow
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
- 存储与慢哈希必须离主线程。生产单例工厂保证单进程一个授权域；域内 tryLock
  串行 worker 事务，并发调用直接拒绝。撤销使用独立原子代际，最终提交在准备 IO
  后与撤销竞争同一原子单元，具体发布顺序见 R86-02。无隐式排队重试或秘密日志。

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
调用者输入缓冲。该版本仍存在 revoke 与完整磁盘 IO 共用锁的问题，随后由 QA
实测确认为 R86-02 合入前阻断；旧失败及本轮协议修复见下文，不能按历史35PASS放行。

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

## root 追加的两文件 CI 测试前置

按 root 在本轮修复期间的明确指令，只取原 M06 仓库
`b3a392a1518eefab9b17595e28a97dc25725a196..1a9f5cd9d083e2ffe27b3354465de04d2206179d`
中以下两文件差异，原样应用，无上下文冲突：

- `app/src/androidTest/java/com/littlebuddy/BuddyActivityTest.kt`：两次唤醒正控均等待
  当前 socket 的 END 之后出现 PCM_BUFFERED 再 Stop，避免本地 END 已入队但服务端
  尚未实际消费完成时过早 Stop。
- `backend/tests/test_animal_cloud.py`：真实本地 TLS 测试控制写入消费/响应时序，
  证明本地 END 和旧连接回执均不足以表示本轮完成；保留 exact2/sealed2 断言。

这两文件只有测试变更，不包含 M06 生产修复、诊断树或 workflow。原 CI97 的
API36 设备36/36和JVM TLS1通过、transport sealed1/exact1未达2的失败由root提供，
本轮未重跑该旧CI；旧失败记录仍保留，不能改记通过。global95/96的API36证据为
root既有实跑报告，不是本轮作者真机/模拟器实测。最终head的外部CI按正常PR触发，
本轮不等待、不将pending算通过，也不另开模拟器或HDA取证。

本轮实际执行 `scripts/with-build-lock python3 -m unittest backend.tests.test_animal_cloud -v`：
**13/13 通过，失败0、跳过0，20.151s，退出码0**，包含新增延迟消费因果负控。
Android instrumentation 两处屏障未在本轮设备执行，原 server transport 2/2 门槛
在 `scripts/android-ci-instrument` 保持原样。

## R86-02：原子撤销与最终提交协议

旧 head `2343130679481f7db17be343db69b57137591589` 的 QA 正常 JVM 分母为
**39项：38通过、1失败、0跳过**，不是35项全绿。失败是实际线程撤销反例，不能用
预期突变负控覆盖。原始失败日志保留在
`docs/testing/v2/r86-02/2343130-recheck-revoke.log`（SHA256
`5c0d0e1c5c73f678c8f41e7b2b99fa38069471f0ab23bd4de4c2a640a439b6ea`）。
旧日志原件记录 `revoke_returned_within_300ms=false write_committed=true stored_volume=80`。
QA 原 `RevocationBoundaryTest.kt` 与两项独立 key 反例已逐字节保留在测试目录；
300ms及时返回和解除提交前阻塞后旧写拒绝的原断言没有修改。

协议与边界：

1. `ParentEpoch` 用同一 AtomicReference 单元排序生命周期失效与最终提交决定。
   HOME/focus/page 的 `revoke/enterPage` 只原子递增 page，不取内存 monitor 或
   worker 锁；旧 grant、验证 epoch、owner challenge 均立即因页代际不符而失效。
   generation 继续区分本页验证尝试；grant 校验同时要求引用同一性、generation、
   原子 page 与闲置期限。300ms只用于受控测试观察，非手机实时性保证。
2. 内存 monitor 仅保护短状态更新，不包含 KDF、OwnerProof、Keystore 或文件 IO。
   独立 worker tryLock 覆盖完整事务/验证，其他 verify/replace/save 直接拒绝，不将
   旧快照排队；revoke 不使用此锁。对外受保护读取在 worker 事务期间拒绝，避免
   最终决定与磁盘回读之间暴露旧内存值。
3. `ParentCommit.checkAllowed` 只是可取消的提前检查，不等于提交。Android
   `ParentRecordFile.publish` 先写 AtomicFile 临时文件、flush、fd.sync，耗时准备
   全部在最终决定之前。**最终逻辑提交线性化点是此后 `claim()` 对同一 epoch
   单元成功的 CAS**，不是 worker 锁入口、KDF开始、早期检查或 startWrite。
   最终判定同时复核 grant/验证代际/owner期限及闲置到期。撤销若先赢，claim抛
   ParentCommitRejected，failWrite回退临时文件，既有记录不发布。
4. CAS先赢表示有效事务已作不可撤回的最终决定；随后 AtomicFile.finishWrite
   执行物理发布（Android仍可能再次sync/close/rename，可能阻塞/失败）。这段时间
   HOME仍原子失效并立即返回，不等磁盘，但不能撤回已经决定的事务。存储完成并
   readback核对后，才更新 witness 和内存 record，然后才报告成功。期间同域无
   第二个存储事务可插入。若物理发布/回读失败则隔离、返回失败、不发布授权或自动
   重试；磁盘可能已有新值，不能谎报已回滚，需后续受审恢复。
5. 包括失败预留在内的所有写都使用同一页代际提交协议。撤销在预留claim前先赢，
   则不写计数也不做KDF，不存在未计数却已验证的尝试；预留已经提交再撤销，则保留
   计数。成功清计数和授grant各自重验页代际，迟到结果不能恢复授权。PIN更新若已
   合法决定后发生HOME，已提交的新PIN保留，但不会复活授权或再次撤销更晚的新页面。
6. 既有事务在最终claim前取消可安全返回LOCKED，不当成磁盘损坏。首次初始化
   已创建alias但取消/落盘失败，仍隔离且不再次生成；R86-01的缺失/失效/替换key、
   记录损坏和磁盘失败策略保留。无真实OwnerProof提供者仍默认拒绝。

这里保证的是受测软件协议的顺序，不是CAS与Android文件系统的跨掉电原子事务。
物理发布不是内存CAS本身；成功返回必须包含文件提交和回读，不能仅凭CAS报成功。
真实KeyStore/AtomicFile掉电与最终宿主生命周期仍待设备验证。

本轮最终源码正常检查：**53/53通过、失败0、跳过0，74.772s，退出码0**；所有
新增Kotlin含Android适配同时编译通过。组成是原35项、原QA2项key反例、原QA2项
撤销反例、11项并发/提交测试与3项生产SealedParentStore准备/发布测试。
原QA反例现在实测 `revoke_returned_within_300ms=true write_committed=false stored_volume=60`。
另覆盖已提交后撤销、CAS决定后物理发布延迟、并发verify/replace/save、KDF/归属证明
阻塞时撤销、expiry、初始化/恢复迟到、成功验证迟到清计数及提交后磁盘故障。
本轮KDF主机样本596/592/585/594ms；OPPO未测。早两轮49/52项通过为补充最终边界前
的中间验证，不与最终53项累加。两类负控另计，不列入正常通过分母。
原作者预留测试将撤销钩子放到已提交之后，
保留已提交计数1的断言；新增独立用例验证预留提交前撤销不写计数且KDF调用为0。

```sh
scripts/with-build-lock env PARENT_ANDROID_JAR=/home/ubuntu/.gradle/caches/8.13/transforms/9ec1aa52f1567b6bf359cfb66d138a5b/transformed/android.jar python3 scripts/v2-parent-tests.py
scripts/with-build-lock env PARENT_ANDROID_JAR=/home/ubuntu/.gradle/caches/8.13/transforms/9ec1aa52f1567b6bf359cfb66d138a5b/transformed/android.jar python3 scripts/v2-parent-tests.py --r86-revoke-negative-control
scripts/with-build-lock env PARENT_ANDROID_JAR=/home/ubuntu/.gradle/caches/8.13/transforms/9ec1aa52f1567b6bf359cfb66d138a5b/transformed/android.jar python3 scripts/v2-parent-tests.py --r86-key-loss-negative-control
```

负控仅临时副本恢复“撤销等待worker锁”或“既有域丢key时重建”，产品源不改。
本轮负控实际结果：撤销负控2项中1项按预期失败（2.908s），输出恢复为
`revoke_returned_within_300ms=false write_committed=true stored_volume=80`；缺key
负控11项中2项按预期失败（4.398s）。两次JUnit均退出1，脚本核对预期后退出0，
均包含Android适配编译。最终负控复跑前两次wrapper因共享锁占用退出75，未启动测试，
获同一锁后正常串行完成；未改wrapper或另建锁。它们不是正常53项中的失败，也不改变旧head39项中的真实失败。
本轮未重跑未变化的TLS/设备/旧CI；上节TLS13/13为前一轮证据，非本轮新增分母。
UI/完整生命周期接线、真实归属/系统恢复/端点、M06音频与A27/A28/A34、D04继续OPEN，
不以纯core线程测试声称手机/音频实测。PR仍需原QA定向复核和root审合。
