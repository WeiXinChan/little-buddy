本轮组合接续 PR41/PR40，固定 base `12aa7a84c23c48e114108fc6fbe9fa7852ce1801`。原两份 UI 文档记录前一阶段边界；本页更新反馈工厂已装配的事实。完整产品、真实归属/Provider 和设备验收仍未完成。

## 实际组合路径

`V2VoiceActivity → AndroidParentPanel → ParentPanelModel → ParentPanelView → AndroidParentFeedbackRoute → FeedbackPageFactory → FeedbackPageHandle`。

默认路由不再空工厂。验证成功后内部导航以 `nextPage` 轮换真实 Grant，工厂仅收到本次 domain/Grant。`ParentFeedbackBinding` 固定这对对象，拒绝不同域、不同 Grant 或已退休句柄；gate 仅把本次短内存 decision 委托 `domain.acceptProtected`，保留最终 claim/CAS 后期限确认。返回的 Boolean 只反映该次同步 decision，既不缓存也不作为后续文件/网络 IO 的许可。M09 已有 core 在 staged 文件后和 provider admission 再次使用同一真实 authorizer。

`ParentRouteSlot` 是实际 Android host 与组合测试共用的句柄所有者。同 revision 复用，换页先释放旧句柄；暂停永不恢复旧句柄。model 在 HOME/失焦/退出/销毁时先定向失效本页；binding 也在调用 handle.pause/close 前原子失效，清理不等待 KDF/Keystore/文件 IO。close 幂等，引用先移除，清理异常不阻止后续页面释放。工厂抛错失效原 Grant，不允许重试同授权；挂载 View 抛错也 close 并锁定模型。

返回管理由创建时 revision 的 onExit 触发：先轮换新管理 Grant，旧句柄再 close，仅 revokePage(旧 Grant)，不误撤销新页。旧回调、旧 host 及旧反馈 intent 无法借用后来 Grant。120s idle 轮询不续期；Activity 的真实本地触摸仍可续期。管理取消回眼睛、物理返回和已有生命周期入口沿用已合代码。

没有复制未合 M09 源码。文件边界已交其活动 run：本 PR 独占 parent、对应组合测试/runner/docs；M09 独占 feedback 后台/进程启动调度及 v2 manifest application 注册，工厂/gate/handle v1 不变。本 APK 不包含其并行分支新增后台启动代码。

## 验证方法与范围

组合测试调用真实 ParentPanelModel、ParentFeedbackBinding、ParentRouteSlot、ParentFeedbackAuthorizer、FeedbackEngine/Core 和 AES 加密文件 vault；不是两个模块测试结果拼接。OwnerProof/父域内存 store、provider、时钟/队列和无 View 的句柄是明确的合成端口。Android 工厂/控件/Activity 均编入完整 APK，但未执行真实控件、IME、物理 HOME 或设备音频。

13 个组合案例：合法提交、返回后设置仍可写、旧回调/close 对新页隔离、HOME 迟到 UI、失焦排队提交、等值 idle、工厂失败、清理异常、不同域/Grant、已完成提交后的关闭、阻塞 staging 时300ms撤销及旧写拒绝、IO期间到期最终拒绝、短 decision 异常。后两者不依赖 host tick 替代最终授权。磁盘为真实私有临时目录，测试结束删除，仅含合成材料。

实际结果与 APK 元数据在本页末尾记录。负控只改临时副本，必须编译成功且命中特定断言；编译错误不算有效。三种变体为借用新 Grant、全域撤销伤新页、移除最终域 gate。旧 R86/R87 失败源码/日志/原断言未修改。

复现（先取既有 heavy.lock，所有重任务串行；无第二锁，Gradle max-workers=1）：

```sh
scripts/with-build-lock env PARENT_ANDROID_JAR=<existing-android.jar> python3 scripts/v2-parent-tests.py --combined
scripts/with-build-lock python3 scripts/v2-parent-tests.py --composition-only
scripts/with-build-lock python3 scripts/v2-parent-tests.py --binding-mutant=borrow
scripts/with-build-lock python3 scripts/v2-parent-tests.py --binding-mutant=scope
scripts/with-build-lock python3 scripts/v2-parent-tests.py --binding-mutant=expiry
scripts/with-build-lock env ANDROID_HOME=<existing-sdk> ANDROID_SDK_ROOT=<same-sdk> ./gradlew --offline --no-daemon --max-workers=1 :app:compileV2DebugKotlin :app:assembleV2Debug
```

本机 SDK 为 M06 工作区已有 `oppo-sdk`，仅共享 SDK 工具、不修改该源码树；API jar 为既有 Gradle 缓存。实际运行使用 workdir 外层 `with-existing-build-lock`，它是仓库 wrapper 的副本，仅将同一锁 `flock -n 9` 改为 `flock -w 45 9`，安全检查/2G cgroup/退出清理不变。没有下载安装 SDK、启服务/部署或重跑旧 CI。

## 仍然缺失的真实资源

| 缺口 | 当前接口/状态 | 所需真实资源与证据 |
| --- | --- | --- |
| 可信设备/家长归属 | AndroidParentRuntime.verifiedDeviceBinding 返回 null，load 默认拒绝 | 经审查的设备绑定 issuer、绑定校验及有效性/撤销证据；不能用安装 ID/Intent extra |
| 初始化/找回 PIN | OwnerProof.consume + OwnerChallenge，生产无 issuer | 真实所有权认证及一次性 challenge、操作/绑定/期限证明；不能默认 PIN/测试 proof |
| 反馈平台 | FeedbackProvider 默认为 Unavailable | 经授权真实 endpoint/auth/device-bound admission、原 idempotency key 与全副本删除回执；未发网络请求 |
| 可信时间/恢复 | AndroidFeedbackClock 仅本地连续性；Keystore/noBackup 本地保护 | 可信时钟及重启/回滚/恢复策略、真实设备绑定和备份恢复反例，未声称能防全副本回滚 |
| 音频/音量执行 | 活跃音频仍拒绝管理；仅安全存本地 volumeLimit | M06 真实管理事件/暂停/零上传/恢复及播放上限执行证据，A27/A28/A34 OPEN |
| Android 实机安全 | 本轮 Linux 编译/打包 | 控件/IME/FLAG_SECURE、物理 HOME、Keystore 丢失/掉电；D04 OPEN |

生产未插入测试 provider/OwnerProof、安装 ID 或默认 PIN。故缺真实归属时入口依旧显示不可用，不能把组合测试解释成实际认证或已可提交平台。M09 后台 OS 调度由独立 PR 交付，本轮没有替其宣称已集成。未占手机/Mac/模拟器/HDA，不把设备恢复作为前置；用户无过程测试待办。

## 本轮实际结果

- 完整组合命令 **197/197 通过、失败0、跳过0，JUnit 164.406s**：父域/管理模型92 + 反馈域92 + 组合13。包含现存 R86/R87 原反例，未把前轮 QA 额外两项混入。
- 同一组合案例进一步补强不同域输入后，最终测试源 **13/13 重跑通过、失败0、跳过0，20.459s**；与197重叠，不累加为210。
- 三种临时突变分别编译成功，各 **1执行/1预期断言失败/0跳过**，三个指定目标均命中，JUnit退出1、runner确认后退出0。负控不计入197正常分母。旧4/12类负控源码保留，本轮未重复重做，不算本轮执行。
- 第一轮中间集合11/11，仅开发检查，不混最终分母。
- Linux 完整 Android 编译 + APK 打包 **成功，1m1s；39任务，27实际执行、12 up-to-date**。编译有既有 onBackPressed 弃用警告，未作为失败；Gradle 条件检查任务跳过不是 JUnit 跳过。
- runner 最后仅将纯 JVM feedback 源选择改为显式五文件白名单，避免未来 Application Android 类进入无 SDK 的负控；已验证当前树新旧源集合完全相同，未改变本轮执行集合。

## APK 交付与安装说明

附件 `little-buddy-v2-integration.apk` 为本树 `:app:assembleV2Debug` 的原字节副本。

| 项 | 实测值 |
| --- | --- |
| applicationId | `com.littlebuddy.sim.v2` |
| versionCode / versionName | `13` / `0.1.12-animal-private-v2-m04`（沿用基线版本名，不据此推断本轮功能；以本 PR SHA 和下列 hash 定位） |
| SDK / ABI | min26 / target36 / arm64-v8a |
| APK SHA-256 | `3e98bea768e3496ffc4224baff192aafc97961b80f8e53b6205842df646b161c` |
| 签名 | 已有 Android Debug 密钥；非正式发布签名，未新建/导出密钥 |
| 证书 SHA-256 | `7705f543347ae9ec1de4ae4b0dc24f73b0a472fb32ecc06cca0d112a8fe75e10` |

`apksigner verify --print-certs` 退出0，`aapt dump badging` 与 metadata 一致。安装说明供后续授权验收使用，本轮没有要求用户执行或占用设备：`adb install -r little-buddy-v2-integration.apk`；入口为 `com.littlebuddy.sim.v2/com.littlebuddy.V2VoiceActivity`。这是独立 V2 包和调试 APK，不替代正式发布；签名不一致不能直接覆盖已有包，不在本轮清除数据/卸载。没有声称已安装、已渲染或已验证声学。CI 由新 PR 正常触发，本轮不等待或冒称通过，不重跑旧 CI。
