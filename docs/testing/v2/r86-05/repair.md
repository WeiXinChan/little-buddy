R86-05：同步重入时的句柄归属与释放

修复前固定head `29317ba8a3ae7b4f7c32b6e458b8c2aaf92293c0` 的独立正常为26执行/25通过/1失败/0跳过。完整QA原包、报告、三项源码、失败日志与QA首次生成编译错误在 `qa-29317ba/` 按原字节归档；编译错误与产品断言分开，不覆盖旧失败。旧929的R86-04源码/失败和原R86/R87归档不变。

## 归属协议与生产调用

生产仍为 `ParentPanelView → ParentRouteSlot.mount → factory/handle`，没有用不可重入假设回避问题。slot由Android主/UI线程访问（AndroidParentPanel的render经主Handler，Activity生命周期/控件事件也在UI线程），支持工厂、present、pause、close及close中再次重入的同步调用。不是跨线程通用容器，不在授权/IO锁中执行回调。

每次新创建使用独立Owner对象，携带ticket、ready状态与page；先把新Owner置为当前，再从旧Owner移除page引用，才调用旧句柄close。旧close中出现新请求会抢占预留Owner，外层返回后先确认身份，失去归属则连旧工厂都不启动。

工厂结果只放局部变量。工厂返回后当前Owner仍是创建时对象才发布并标为ready；否则只close刚返回的旧结果，不读写新Owner。旧结果的close再次重入时，之后也没有覆盖新页的写。Owner对象身份还区分“取消后又使用同ticket”的不同创建，避免仅比较Long的ABA；真实model revision本身单调推进。

mount只呈现仍归属当前且ready的结果；同ticket工厂递归不把未完成构造当成失败。present抛错后再次检查Owner，已被新页抢占不调用旧失败恢复。close在回调前清当前引用；close(ticket)只匹配当前ticket，旧ticket不伤后来页面。pause回调后也不写回旧状态。

端口契约为工厂独占转移其返回句柄（真实Android工厂每次新建page/handle）；未返回前抛错的部分构造仍由工厂负责。close回调异常可被隔离以继续导航，测试的“恰好一次”是对每个返回句柄的close调用次数，不能当成OS/堆/底层资源释放成功证明。没有缓存Grant、accepted Boolean或恢复旧权限；R86-04后台!active及无Grant锁定页路径未修改。

## 本轮执行范围

开发中40项曾全部通过（38.745s）；随后补清理回调取消两项。最终集合42项：原组合20＋前QA3＋本QA原3（含原失败断言）＋新同步重入16。原QA RecoveryBoundaryTest源码逐字节执行，原“new route handle lost…”与“retired factory handle leaked…”断言均保持。新16覆盖工厂/释放回调抢占、丢失结果释放再次重入、工厂/呈现/清理异常、取消、同ticket不同创建、同ticket构造递归、pause、空结果失败恢复及嵌套释放链；检查所有已返回句柄close一次与新页不丢失。真实domain/Grant/engine/core/AES文件的既有组合例继续覆盖无Grant锁定页验证/取消、HOME/open抢占、旧host/newGrant、阻塞IO最终gate与Provider admission期限。

当前分母不是旧作者115或独立26；未重跑未变化父域92、feedback92、云/声学/旧CI，不将历史通过混入本轮。生产仅改ParentRouteSlot，未混PR43后台/manifest或M06/V1。

四类原负控borrow/scope/expiry/recovery按影响重跑；另增：恢复29317旧slot命中QA原重入失败；把预留Owner移到旧close之后命中释放回调抢占反例。每种只在临时副本编译，需编译成功且指定单目标RESULT 1 1 0，负控单列、不计正常通过。

```sh
scripts/with-build-lock env PARENT_ANDROID_JAR=<existing-android.jar> python3 scripts/v2-parent-tests.py --composition-only
scripts/with-build-lock python3 scripts/v2-parent-tests.py --binding-mutant=borrow
scripts/with-build-lock python3 scripts/v2-parent-tests.py --binding-mutant=scope
scripts/with-build-lock python3 scripts/v2-parent-tests.py --binding-mutant=expiry
scripts/with-build-lock python3 scripts/v2-parent-tests.py --binding-mutant=recovery
scripts/with-build-lock python3 scripts/v2-parent-tests.py --binding-mutant=reentry
scripts/with-build-lock python3 scripts/v2-parent-tests.py --binding-mutant=dispose-reentry
scripts/with-build-lock env ANDROID_HOME=<existing-sdk> ANDROID_SDK_ROOT=<same-sdk> ./gradlew --offline --no-daemon --max-workers=1 :app:compileV2DebugKotlin :app:assembleV2Debug
```

实际运行沿用workdir外层with-existing-build-lock，唯一差异是同一heavy.lock等待45s，保留原权限检查/2G cgroup，无第二锁。SDK/API jar均现有资源。不派Mac/手机/模拟器HDA，不要求用户过程操作。JVM同步重入可复现不代表已在Android平台发生该重入，也不作为物理HOME/音频/实机Keystore证据。真实归属恢复D04、Provider、可信时钟设备绑定继续OPEN、默认拒绝。新CI结果不计通过，待原QA/root。


六类负控实际均编译成功：borrow/scope/expiry/recovery/reentry/dispose-reentry 各1执行/1预期断言失败/0跳过；JUnit退出1，runner核对指定目标后退出0。reentry执行原QA `factoryReentryMustNotOverwriteNewHandleOrLoseRelease`，dispose-reentry执行 `oldCloseReentryPreemptsOuterFactoryBeforeConstruction`。共6次执行/6预期失败，与正常分母分开。

最终正常 **42/42、失败0、跳过0，37.534s**，同次实际Android适配器API编译成功。开发中40项与此重叠，不累加。旧QA26项25过1失败仅作为原件历史保留；本次3项原QA源码未改而全部通过。

完整Android离线编译＋APK打包成功 **42s，39任务/4执行/35 up-to-date**，max-workers=1、heavy.lock独占。Gradle条件检查SKIPPED不是JUnit跳过。新APK `little-buddy-v2-r8605.apk` SHA-256：**`87a26ebda78c3fc65c0f52edd41c1356d96b15b169809b0ecff17e7e0fa5d651`**，附件是此次输出原字节副本。

版本/签名：包 `com.littlebuddy.sim.v2`，versionCode13，沿用版本名 `0.1.12-animal-private-v2-m04`，min26/target36、arm64-v8a；用固定新head/tree及APK hash区分修复。已有Android Debug证书SHA256 `7705f543347ae9ec1de4ae4b0dc24f73b0a472fb32ecc06cca0d112a8fe75e10`，apksigner核验退出0，aapt/metadata一致。未新建/导出密钥，不是正式发布。

后续授权验收的安装说明：`adb install -r little-buddy-v2-r8605.apk`，入口 `com.littlebuddy.sim.v2/com.littlebuddy.V2VoiceActivity`；签名不一致不能直接覆盖，不在本轮卸载或清数据。未安装或部署，不将编译和同步JVM重入当作Android平台实际重入/物理HOME/声学/实机Keystore证明。真实归属/Provider等缺失默认拒绝、继续OPEN，无用户过程动作。
