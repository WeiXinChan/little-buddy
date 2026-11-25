R86-04：前台反馈挂载失败后的可交互恢复

旧固定 head `929f2919c2767b7174f6ede5d23141317558319e` 的独立正常结果为17执行、16通过、1失败、0跳过。197/197及旧APK一致性不能覆盖该真实失败。原报告、源码、失败日志和完整QA证据zip在 `qa-929f291/` 按原字节归档；不改成成功记录。

## 修复与最终调用

`ParentPanelView` 通过 `ParentRouteSlot.mount` 执行实际工厂/挂载边界，工厂返回空、抛错或 `setContentView` 抛错均进入 `model.routeFailed(创建时 revision) { routes.close(同 revision) }`。

`routeFailed` 只接受仍然前台 active 的当前反馈页，先 invalidate（原子定向撤销原页、清 Grant/PIN、推进 revision），再释放句柄。之后仅在未出现后来生命周期/路由 revision 的情况下激活一个无 Grant 的锁定验证页，提供当前 viewToken 对应的验证和取消。此步骤不 enterPage、不恢复旧 Grant；只有重新输入 PIN 才发起新页验证，因此不会撤销其间另一个 host 的新 Grant。

后台 `pause` 仍保持 inactive，`userAction(!active)` 的拒绝原样保留。若清理期间 HOME/pause、open 或新路由重入，新的 revision 优先，旧恢复不激活后台、不覆盖新页。迟到失败只定向 close 原 slot ticket，不关闭后来句柄。close 先释放引用、binding先撤销后清理，清理异常也不留下死锁页面。

这不是把原QA反例中的 `pause` 改成后台可交互：该旧序列已从前台错误处理撤下，原源码/原失败必须保留。修复回归使用生产共用 `slot.mount → routeFailed` 注入挂载失败，保持QA原 VERIFY、LOCKED、取消 accepted=true 三项断言及提示不变。没有声称在Android上实际注入了平台挂载异常。

## 范围与反例

新增7项：挂载失败取消可操作并重新进入；工厂失败同样恢复；恢复后必须重新验证且旧按钮/回调拒绝；清理异常仍可取消；清理期间HOME不得激活后台；迟到挂载失败不得关闭新句柄；清理期间另一个host新Grant不受影响。

现有13项组合与QA原3项也纳入：旧host/newGrant、迟到UI/返回/idle、staging阻塞300ms撤销、最终期限和落盘后Provider admission重验。QA3项源码从附件逐字节进入 `IndependentCompositionTest.kt`，未改断言。

正常修复集合为父域/模型92＋组合20＋QA3＝115；定向23与之重叠，不另加分母。原feedback92未修改且本轮不机械重复执行；原197是旧head历史作者证据，不作为新head或独立QA分母。

三类原负控borrow/scope/expiry按影响重跑，另增recovery负控：仅临时副本将前台恢复留为inactive，必须再次命中原“当前取消应可操作”断言。每种编译成功、单目标1执行/1预期断言失败/0跳过，负控与正常分母分开。旧R86/R87其他原断言/负控/失败未改。

```sh
scripts/with-build-lock env PARENT_ANDROID_JAR=<existing-android.jar> python3 scripts/v2-parent-tests.py --r86-04
scripts/with-build-lock env PARENT_ANDROID_JAR=<existing-android.jar> python3 scripts/v2-parent-tests.py --composition-only
scripts/with-build-lock python3 scripts/v2-parent-tests.py --binding-mutant=borrow
scripts/with-build-lock python3 scripts/v2-parent-tests.py --binding-mutant=scope
scripts/with-build-lock python3 scripts/v2-parent-tests.py --binding-mutant=expiry
scripts/with-build-lock python3 scripts/v2-parent-tests.py --binding-mutant=recovery
scripts/with-build-lock env ANDROID_HOME=<existing-sdk> ANDROID_SDK_ROOT=<same-sdk> ./gradlew --offline --no-daemon --max-workers=1 :app:compileV2DebugKotlin :app:assembleV2Debug
```

实际 wrapper 为外层 `with-existing-build-lock`（仅原heavy.lock等待45s，权限检查/cgroup保持），共享已有SDK/API jar；不新建锁，不动M06树。无变化云/声学/旧CI未重跑；不占手机/Mac/模拟器mic/HDA，无用户过程操作。519后台/manifest域未修改。归属初始化恢复/D04、Provider、可信时钟绑定、物理音频/IME/HOME/Keystore掉电仍OPEN且默认拒绝。

## 实际结果

定向23/23，失败0、跳过0，34.478s，Android适配器API编译成功。其余结果及新APK元数据于收口后记录。

正常最终集合 **115/115，失败0、跳过0，163.052s**，同次编译包含实际Android适配器。定向23/23为其中子集，不累加。

四类负控实际完成：borrow/scope/expiry/recovery 各编译成功，各 RESULT 1 1 0（1执行、1预期断言失败、0跳过）。JUnit退出1，runner逐一检查指定目标后退出0；共4次执行/4预期失败，不混入115。recovery 命中 `failedMountMustKeepRenderedCancelOperable` 原取消断言。

完整Android `:app:compileV2DebugKotlin :app:assembleV2Debug` 离线成功 **50s，39任务/4执行/35 up-to-date**，max-workers=1；未将Gradle条件任务SKIPPED计为JVM跳过。APK SHA-256 **`44d6c15999a9bcdb3893c41796565589204aeaf8c047c80b2d2538619a1cc87c`**，附件 `little-buddy-v2-r8604.apk` 与本次输出逐字节相同。旧APK及其旧hash仍保留在原交付评论，不能代本次修复包。

包 `com.littlebuddy.sim.v2`，versionCode13，versionName沿用 `0.1.12-animal-private-v2-m04`，min26/target36、arm64-v8a；不以基线版本名代表本轮功能，以新固定head/tree及APK hash识别。使用已有Debug签名、非正式发布，未新建/导出密钥；apksigner核验退出0，证书SHA256 `7705f543347ae9ec1de4ae4b0dc24f73b0a472fb32ecc06cca0d112a8fe75e10`。aapt与metadata一致。

安装说明供后续授权验收：`adb install -r little-buddy-v2-r8604.apk`，入口 `com.littlebuddy.sim.v2/com.littlebuddy.V2VoiceActivity`；本轮未安装/部署/实际注入Android挂载异常。签名不一致不能直接覆盖，不执行卸载或清数据。真实归属缺失仍默认拒绝，未接测试proof，不要求用户过程操作。新CI结果未采集、不计通过，原PR交独立QA/root，不自行合并。
