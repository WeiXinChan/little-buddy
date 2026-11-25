PR42 独立验收：条件通过，挂载异常恢复项需原作者修复后复核

固定base `12aa7a84c23c48e114108fc6fbe9fa7852ce1801`、远端head `929f2919c2767b7174f6ede5d23141317558319e`、tree `1241d5c1f488930450afa94d47118228edb86eff` 均一致。独立隔离目录运行，未改作者代码、未合并。7文件 +408/-17，限定parent/组合测试/runner/docs；feedback/V1/M06/manifest/workflow未变。

R86-04，P2：反馈View挂载失败后，展示验证页的全部按钮失效。

生产路径在 `app/src/main/java/com/littlebuddy/v2/parent/ParentPanelView.kt:38` 执行setContentView；异常分支第39行先routes.close，再model.pause。`ParentPanelModel.kt:57` invalidate把active设false；第63行pause随后show VERIFY/LOCKED，实际渲染出验证、忘记PIN、取消按钮。但View第52行所有按钮均调用userAction，而Model第32行对!active直接拒绝。Activity本身仍前台有焦点，未必收到新的open；当前页既不能验证也不能按“取消”返回眼睛，直到额外系统返回/焦点往返等外部恢复。

独立 `MountFailureTest.failedMountMustKeepRenderedCancelOperable` 对同一真实model/slot执行生产异常分支的两步恢复：确认VERIFY和父域LOCKED，然后用当前viewToken触发“取消”，得到false。1项执行/1失败/0跳过，原日志完整保留。此测试是JVM恢复路径反例，未在Android系统上注入真正的setContentView异常；真实调用对应关系由上述源码确证。它不是原来HOME/pause应保持可交互的断言，而是前台挂载失败后仍显示可点击页面的恢复契约。

建议最小修复：失败时仍先关闭句柄并撤销该页，然后显式退出到眼睛，或以新revision恢复可交互的锁定/不可用页（不恢复旧Grant）。保留真实后台pause的inactive语义，不通过放宽userAction(!active)解决。为此异常分支保留失败注入回归：句柄至多释放一次、旧Grant拒绝、取消可返回、重新验证需新页、旧callback不能复活。建议root在修复定向复核前HOLD合入；没有发现本增量授权绕过。无需真机或改动音频来修复此项。

本轮独立执行分母

| 集合 | 执行 | 通过 | 失败 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| 当前源码新增13组合案例 | 13 | 13 | 0 | 0 |
| QA新增跨阶段/定向撤销 | 3 | 3 | 0 | 0 |
| QA前台挂载失败恢复反例 | 1 | 0 | 1 | 0 |
| 正常源码合计 | 17 | 16 | 1 | 0 |
| 三类突变（各单独案例，预期失败） | 3 | 0 | 3预期 | 0 |

13项20.304s；QA3项4.647s；失败反例1.662s。三类临时源码突变均编译成功：borrow命中“borrowed new Grant”；scope命中设置保存77却仍60；expiry命中Provider发送计数应0却1。均RESULT 1 1 0，JUnit退出1、runner识别后退出0，未将编译错误或负控当正常通过。未机械重跑作者197项或无变化云/音频；作者197/197仅作历史作者证据，不改写成独立197。

通过的实际路径与边界

`ParentRoutes.kt:18` 默认实际适配器创建ParentFeedbackBinding，传入固定domain/Grant和gate至FeedbackPageFactory，再把handle.pause/close包在binding失效之后；`ParentPanelView.kt:24`实际使用受测ParentRouteSlot。`ParentFeedbackBinding.kt:14`严格比对domain和Grant对象，最终调用domain.acceptProtected，不缓存Boolean用于后续IO，短decision的published仅表示本次同步调用。

`ParentPanelModel.kt:139`返回先nextPage换Grant，再渲染时释放旧句柄；binding第30行定向revokePage不伤新页。失焦/HOME/退出/idle路径先model失效再handle清理，原有期限CAS、120s不自动轮询续期未变。3项QA补测：本地materials落盘后Provider admission前到期仍拒绝；staging被真实文件IO钩子阻塞时返回在300ms内完成、旧提交被拒且新管理页可保存83；工厂中先创建后页再抛错仅撤旧页，后页Grant仍有效。

13项组合真实使用ParentPanelModel、binding/gate、ParentFeedbackAuthorizer、FeedbackEngine/Core、AES文件vault；owner/provider/clock/队列与无View句柄为合成端口。不能当成实际Android工厂构造、控件IME或物理HOME已执行；真实工厂链有源码核查和完整模块编译证明。后确认成功的特定本地事务允许其后完成IO，但Provider admission仍重新核原Grant，这由独立跨阶段反例验证。

版本/归档/APK

两份作者报告和证据包、APK经认证CLI读取，报告字节与仓库一致，作者identity中7份源哈希均匹配本树。R86原失败日志和所有R86/R87原断言均未改（仅新组合测试增加），证据identity.txt记录历史日志哈希。234旧39项38通过1失败、ab60旧55项54通过1失败继续是历史失败事实，不进入本轮分母。

APK附件SHA256确为 `3e98bea768e3496ffc4224baff192aafc97961b80f8e53b6205842df646b161c`，apksigner独立验证退出0；Debug证书SHA256 `7705f543347ae9ec1de4ae4b0dc24f73b0a472fb32ecc06cca0d112a8fe75e10`。aapt独立读取包com.littlebuddy.sim.v2、versionCode13、min26/target36/arm64-v8a。没有安装或部署。

独立完整Android编译/打包成功59s，39任务27执行/12 up-to-date；配置检查条件任务SKIPPED不是JVM跳过。原有onBackPressed弃用和原生库不能strip提示，不影响构建成功。独立重建整APK SHA256与交付附件完全一致，5个DEX及manifest字节也一致，见apk-comparison.json；本次未发布重建APK。

真实归属初始化/恢复、Provider、可信时钟设备绑定仍缺资源并默认拒绝；AndroidParentRuntime绑定null。完整M08/M09、音频管理/音量执行、物理HOME/IME/Keystore掉电、A27/A28/A34/D04继续OPEN。未争写519后台调度，未占手机/模拟器/HDA，不等待或记新CI通过。

复现：从固定head独立checkout，在现有heavy.lock独占下执行：

```sh
../qa41/with-build-lock-wait python3 scripts/v2-parent-tests.py --composition-only
../qa41/with-build-lock-wait python3 ../qa42/independent.py --composition-only
../qa41/with-build-lock-wait python3 ../qa42/negatives.py
../qa41/with-build-lock-wait python3 ../qa42/mount-failure.py --composition-only
../qa41/with-build-lock-wait env ANDROID_HOME=<existing-sdk> ANDROID_SDK_ROOT=<same-sdk> ./gradlew --offline --no-daemon --max-workers=1 :app:compileV2DebugKotlin :app:assembleV2Debug
```

包装只将既有锁等待改为45s，未建第二锁。QA独立脚本沿用源runner编译配置，仅替换测试目标和ROOT；重新定位时需改ROOT。首次QA shell调用误用相对工作目录，重定向前失败、未执行测试，已修正工作目录；未计为测试断言或重型构建失败。
