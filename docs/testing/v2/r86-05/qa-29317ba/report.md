PR42 R86-04 修复版独立定向复核

结论：原R86-04修复通过；新增重入句柄归属反例失败，建议PR42继续HOLD，交原b30最小修复后再定向复核，root最终审合。未改作者源码/未合并。

版本：固定base `12aa7a84c23c48e114108fc6fbe9fa7852ce1801`；远端head `29317ba8a3ae7b4f7c32b6e458b8c2aaf92293c0`、tree `ee4371fdac2f07a0e05cc50580b859213fdd2849` 均匹配。相对929修改14文件，生产仅ParentPanelModel/ParentPanelView/ParentRouteSlot；其余新增测试/归档/文档和runner。未混PR43后台、M06、V1、manifest或workflow改动。

R86-05（P2）：工厂重入新ticket后，旧factory返回覆盖新句柄，导致释放归属错误。

`app/src/main/java/com/littlebuddy/v2/parent/ParentRouteSlot.kt:12` close后设置ticket；第13行不检查仍拥有该ticket便将factory返回值写入page。第20行mount只在覆盖已经发生后检查revision，不能恢复被覆盖的新句柄。

独立失败调用顺序：mount(1)工厂内同步mount(2)并成功present Handle2；旧工厂返回Handle1。此时revision仍2、page却被覆盖成Handle1；旧mount因revision不匹配返回。随后close(2)实际关闭Handle1，Handle2从slot丢失、未关闭。原输出closed=[1]，断言“new route handle lost during reentrant factory”失败。旧Handle1也不是在丢失归属时立即关闭，而被错误保留到新ticket退出。

`RecoveryBoundaryTest.factoryReentryMustNotOverwriteNewHandleOrLoseRelease`直接运行生产共用slot，测试没有修改它或替换其实现，使用合成句柄/同步重入工厂。此项未证明当前Android工厂发生过真实平台重入，也未证明授权绕过；它证明本次要求的“新路由抢占/旧ticket不得伤新页、失败释放”在共用边界下没有完整保证。Android实际host直接调用同一mount（ParentPanelView第32行），故建议合入前处理。

建议最小方案：factory返回先保存在局部，仅当仍拥有创建时ticket时发布到slot；丢失归属则定向释放刚返回的旧句柄且保留新page。close旧页本身也可能重入，close返回后、设置新ticket前须确认未被新页面抢占。mount不应呈现已退休结果。补保留原例及close回调重入的同类反例，不用全域close/revoke或恢复旧Grant解决。若选择不支持同步重入，需给出工厂/清理端口的可执行约束及实际host满足该约束的证据；本次未证明当前Android工厂现实中已触发此重入。未自行改作者代码。

正常源码实际分母

| 集合 | 执行 | 通过 | 失败 | 跳过 |
| --- | ---: | ---: | ---: | ---: |
| 作者新增/现有定向组合20＋QA原3 | 23 | 23 | 0 | 0 |
| QA新增恢复/重入边界 | 3 | 2 | 1 | 0 |
| 本轮合计 | 26 | 25 | 1 | 0 |

23项34.848s；QA额外3项3.417s，见boundary.log。作者115/115未冒充独立分母，定向23为其子集不累加。旧929原17项16过1失败仍单列历史。首次QA新测试生成漏class关键字导致编译失败，原输出另存boundary-compile-error.log；修正QA文件后编译成功再得上述断言失败，不计编译错误为产品测试/负控。该确定性断言仅执行一次，未反复重试或修改断言。

已通过的R86-04范围

实际host改用slot.mount→model.routeFailed(创建时revision)；routeFailed先invalidate（定向撤销原页、清Grant/PIN、推进revision），再release；只有未被后来生命周期/路由抢占时激活无Grant锁定验证页。原userAction !active拒绝未变，后台pause仍inactive。当前取消可退出、必须新PIN验证才有新Grant、旧按钮/迟到回调拒绝、清理期间HOME不重新激活、旧ticket失败清理不关闭已存在新页均通过。

QA补测open在失败清理中重入后，新VERIFY页可重新验证且旧close不伤新保存（86）；另一例确认release前原Grant已失效且当前取消可操作。staging阻塞300ms撤销、IO期间到期最终gate、落盘后Provider admission到期拒绝等现有23项本次重新执行通过。

原件与断言

旧QA MountFailureTest.kt/mount-failure.log/report.md/evidence.zip与本代理原件逐字节一致；完整旧zip含17项原输出，未覆盖历史失败。QA原3项源码与新增到仓库测试副本逐字节一致。原VERIFY、LOCKED、取消accepted=true及其失败提示在新挂载异常测试中逐字保留；原slot.close/model.pause序列未被改成后台可交互。作者repair附件等于仓库、identity全部源哈希一致，见identity.txt。R86/R87其他旧反例/失败未改。

仍OPEN：真实Android挂载异常注入、控件IME/物理HOME/音频/实机Keystore掉电、真实归属初始化恢复D04、Provider与可信时钟绑定；缺失仍默认拒绝。无手机/Mac/模拟器/HDA、云调用或用户过程动作，未重跑无变化音频/旧CI，未争写519调度。

复现命令（独立checkout；重任务既有heavy.lock独占，包装仅改同一锁等待45s，Gradle max-workers=1）：

```sh
../qa41/with-build-lock-wait python3 scripts/v2-parent-tests.py --composition-only
../qa41/with-build-lock-wait python3 ../qa42repair/boundary.py --composition-only
../qa41/with-build-lock-wait python3 ../qa42repair/negatives.py
../qa41/with-build-lock-wait env ANDROID_HOME=<existing-sdk> ANDROID_SDK_ROOT=<same-sdk> ./gradlew --offline --no-daemon --max-workers=1 :app:compileV2DebugKotlin :app:assembleV2Debug
```

QA boundary runner继承前轮固定编译配置，仅选额外类，跨机器须调整ROOT。所有原始输出和源码随证据zip交付。

四类独立突变负控结果：borrow/scope/expiry/recovery各1执行、1预期失败、0跳过，合计4/4预期失败。四次均编译成功，JUnit退出1，runner核指定目标与RESULT 1 1 0后退出0。borrow命中borrowed new Grant；scope命中77实际60；expiry命中发送应0实际1；recovery命中原取消断言。它们不混入正常26项分母。

APK附件认证下载后SHA256为 `44d6c15999a9bcdb3893c41796565589204aeaf8c047c80b2d2538619a1cc87c`；独立apksigner核验退出0，Debug证书SHA256 `7705f543347ae9ec1de4ae4b0dc24f73b0a472fb32ecc06cca0d112a8fe75e10`。aapt核包com.littlebuddy.sim.v2、versionCode13、min26/target36/arm64-v8a。未安装/部署。

独立完整Android编译/打包BUILD SUCCESSFUL in 49s，39任务/4执行/35 up-to-date。重建APK与修复附件逐字节相同，SHA256一致，见apk-comparison.json。Gradle条件检查SKIPPED不是JUnit跳过。
