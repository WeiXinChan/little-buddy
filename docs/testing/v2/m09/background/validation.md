# 后台清理：验证及制品边界

固定base `12aa7a84c23c48e114108fc6fbe9fa7852ce1801`；独立工作树 `m09-background`，分支 `agent/tita-87-background`。新代码不包含b30尚未合入的路由组合。

## 实际正常验证

最终JUnit **111执行、111通过、0失败、0跳过**：已合feedback回归92项＋后台/所有权/OS执行票据19项。实际Android API编译包含main12aa的feedback、parent及页面/JobService/Application；时钟、Provider、页授权、工作/UI队列及Job注册端口为合成输入。真实PrivateVaultFiles/AES-GCM、真实Linux FileChannel锁及另一个JVM进程的冲突/释放均执行，后者不是Android文件系统或进程死亡实测。源SHA-256与输出见baseline.json/.log。

19项覆盖启动无需家长页/PIN的实际vault到期补扫、重复启动/周期补扫、16线程请求合并、匹配任务不重排/缺失注册重试、注册失败/异常不阻塞清理、实际存储锁冲突/重试、初始化失败释放锁、第二JVM冲突与teardown释放、写盘失败首次重试及已发布核心持续隔离、部分过期、撤销页、OS stop/旧回调拒绝/失败retry、注册IO不得覆盖后来编辑、默认Provider不可用与离线无正文outbox/较早截止。

中间109项通过后增加跨JVM及离线outbox反例，最终111报告覆盖全部；锁冲突exit75未启动测试，不计入测试失败/跳过分母。原历史R87-01/02/03失败、QA原断言和旧缺SDK失败原件继续原样留在此前目录，未用新成功覆盖旧失败。

## 标准APK

借用b30给定的只读Android SDK36/build-tools35工具目录，只访问SDK，未读写M06源码。重构建经同一scripts/with-build-lock，Gradle `--offline --no-daemon --max-workers=1`，单worker编译。`:app:assembleV2Debug` **exit0，BUILD SUCCESSFUL，64秒，39 tasks executed**，原件apk-build.log。没有安装大型SDK或改变共享构建锁。

APK：`app-v2Debug.apk`，**27214949 bytes**，SHA-256 `a99892ea9f976c9b120c1d0b3fb884638bda49bd92d4ec96cc7813a21923ba5b`。

apksigner verify通过；debug签名证书SHA-256 `7705f543347ae9ec1de4ae4b0dc24f73b0a472fb32ecc06cca0d112a8fe75e10`。未更改签名配置或提交密钥。

`scripts/verify-m09-background-artifact.py` 对真实APK与合并manifest/编译类完成静态核验：V2 Application注册、同进程受BIND_JOB_SERVICE保护的现有service及boot permission、Launcher仍只有V2VoiceActivity；APK DEX含Application，编译字节码有Application→Runtime.start→Maintenance.start、JobService→JobRuns.start实际调用。签名/字节码与manifest哈希见artifact.json，静态核验不计入JUnit分母。

该APK是main12aa＋后台增量，**不是b30未合路由组合APK**，未安装/启动于设备。旧缺SDK失败仍是历史事实，本轮由新获只读SDK资源完成构建；不把此前API jar成功改称旧构建成功。

## 复现

```sh
scripts/with-build-lock python3 scripts/test-m09-core.py --android-jar "$ANDROID_API_JAR" --out build/m09-core/background-final-baseline.json
scripts/with-build-lock python3 scripts/test-m09-core.py --negative-controls --out build/m09-core/background-negative.json
ANDROID_HOME="$EXISTING_SDK" ANDROID_SDK_ROOT="$EXISTING_SDK" scripts/with-build-lock ./gradlew :app:assembleV2Debug --offline --no-daemon --max-workers=1
scripts/with-build-lock python3 scripts/verify-m09-background-artifact.py --sdk "$EXISTING_SDK" --apk app/build/outputs/apk/v2Debug/app-v2Debug.apk --manifest app/build/intermediates/merged_manifest/v2Debug/processV2DebugMainManifest/AndroidManifest.xml --classes app/build/tmp/kotlin-classes/v2Debug --out build/m09-core/background-artifact.json
```

Android API jar SHA-256 `7123df2cceaebc66f3991a480964968c9d9603f6abd542ea8878c39db70fcb07`。纯JVM负控排除main12aa新增的Android parent视图文件，不修改它们；API编译与APK仍编译全部生产源码。

## OPEN

实际Android Application/JobService/OS重启/Doze/强停/未解锁、Keystore及屏幕执行未测，不能承诺精确物理截止或String覆写。生产入口已注册并构建，执行实证止于可移植生产调度逻辑、文件/进程锁和APK静态调用。可信服务时间/设备绑定、真实归属恢复/D04、Provider/全部副本与备份删除缺失仍默认拒绝；未新增网络路径，真实TLS执行0，不连接模拟服务冒充平台。完整M09/A24–A31/D02D06、物理音频/真机Keystore继续OPEN。

无Mac/手机/模拟器mic/HDA派工，无新部署/收费/用户过程操作；不自行合并，原QA独立复核后root审合。

## 最终负控

16个突变均独立编译成功，各执行1项、1预期断言失败、0跳过，16/16检测有效；主命令exit0为全部检测有效，不是正常断言通过。原12继续有效，新增4种分别移除启动补扫、忽略实际FileLock冲突、匹配Job仍反复register、将Engine页面/版本绑定延迟到注册worker后。四种均命中对应真实材料/锁/调度/编辑断言，完整trace与最终源哈希见negative.json/.log，不以编译/初始化错误冒充。

最终分母：JUnit正常111/111，失败0/跳过0；独立负控16编译、16预期断言失败、跳过0。标准Gradle构建1次成功，APK静态检查1次成功，均与JUnit分母分开。
