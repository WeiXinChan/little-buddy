历史诊断说明，仅适用于固定PR120/7fdfb560，不是本分支修复包。

RC8 PIN 初始化诊断（不含竞态修复）

基线固定 cf187d4d35490726e3ce996c6cbe3df678a65a67；独立 V2 包
com.littlebuddy.sim.v2，versionCode 22，诊断名 2.0.0-rc8.pin.diag1。
原 RC8 的资源 manifest、协议、签名身份、授权/期限/原子提交逻辑保持。
不是 RC9，也不是已修复包。不操作手机；待 root 独立审查后协调一次复现。

正常构建 PIN_INIT_DIAGNOSTICS=false。只有 V2Debug 构建显式使用
-PpinInitDiagnostics=true 才启用；V1/debug/release 默认关闭。
诊断构建同 code22、同签名，Android 普通覆盖升级无需自增版本；此为静态资格，
并非已实际安装成功。不得卸载/清数据。回滚使用已归档原 RC8 code22 APK，
同包同签正常覆盖（不使用清数据、强制降级或绕过认证）。root 统一执行。

日志只输出专用 tag V2PinInitDiag；只有进程临时 flow 序号、单调毫秒、固定
stage/reason 枚举。无用户内容、PIN、长度、哈希、盐、nonce、签名、binding、
凭据、异常消息/堆栈。异常只有 SECURITY_ERROR / IO_ERROR / STATE_ERROR /
OTHER_ERROR。认证/UI 线程不做日志 IO；无等待的有界投递，独立线程输出，
进程合计最多 256 条，启用后 15 分钟到期。诊断故障隔离，不参与授权结果。
root 应在复现前确认新诊断进程和采集就绪，勿因日志已过期要求用户再重复操作。

root 后续采集（作者不执行；不采全量 logcat）：

    adb logcat -v raw -s V2PinInitDiag:I '*:S' > pin-init-enums.txt

先正常退出旧页/应用，由 root 启动新诊断进程，采集需在系统认证前就绪。
不要求用户提前再输一次，不清日志/用户数据，不导出应用内部文件。

关键顺序：PROMPT SUCCESS → TAKE SUCCESS → RECEIPT BEGIN/SUCCESS → APPROVE
SUCCESS → SAVE BEGIN → CONSUME SUCCESS → DERIVE → COMMIT → RESULT。
PAGE INVALIDATED / PAGE NO_FOCUS、TICK SAVE_IN_PROGRESS /
TICK TICK_OWNER_INVALID、RESULT STALE_CALLBACK 能区分页面撤销与工作结果。
RESULT UNOWNED 不代替前序失败原因。早退、过期、consume 拒绝、KDF 异常、
commit 拒绝和 IO 隔离分别保留固定枚举证据。

代码检查：保存按钮先 take() 独立 CharArray 后才 setOwnerPin()。
busy render 会 clear EditText，但不会以该 Editable 清除已提取数组。
不能据此证明 OPPO 根因；失焦/lifecycle 仍须观察。

可控离线竞态已复现，尚非真机根因结论：
replacePin 消费 challenge 后清内部 challenge，再做 KDF/提交；页面仍保留
ownerChallenge。阻塞 hasher 或 commit 并调用真实 tick，tick 判旧 challenge
失效，撤销 page、清 pending，最终 commit 拒绝且 UNOWNED。
诊断包故意保留原行为，不在首次诊断中混入修复。

    scripts/with-build-lock python3 scripts/pin-diagnostic-tests.py
    scripts/with-build-lock python3 scripts/pin-diagnostic-tests.py --regression --original
    scripts/with-build-lock python3 scripts/pin-diagnostic-tests.py --regression

第一项为 8 个诊断/安全检查。后两项是未弱化的期望保存成功反例，原 RC8 与
本诊断分支预期各 4 项中 2 项真实失败：hash/tick、commit/tick；过期和取消
仍应通过拒绝断言。反例放在 fixtures，避免故意失败混入常规 JVM 测试发现。
不把该两失败说成诊断 8PASS 已修复；证据原件独立保留。

构建（既有 SDK、debug 签名，不读取或打印私钥；全局重任务串行）：

    scripts/with-build-lock ./gradlew --offline --no-daemon --max-workers=1 \
      -PpinInitDiagnostics=true -Pv2Test :app:testV2DebugUnitTest \
      --tests com.littlebuddy.v2.parent.PinDiagnosticTest \
      --tests com.littlebuddy.v2.parent.ParentPanelModelTest \
      --tests com.littlebuddy.v2.parent.ParentCompletionTest :app:assembleV2Debug

APK：app/build/outputs/apk/v2Debug/app-v2Debug.apk。
metadata / verifier 必须显式 --pin-init-diagnostics；普通校验仍只认原 RC8 名。
移除：丢弃该独立分支或恢复 RC8；普通构建不带开关即禁用诊断。
未进行设备安装、用户复现、云调用、后端部署；不能声称已修好 OPPO PIN 初始化。
