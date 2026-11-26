RC8 PIN 保存修复候选 pin.fix1

精确 RC8 基线 cf187d4d35490726e3ce996c6cbe3df678a65a67；独立分支
agent/tita-86-rc8-pin-tick-fix。包含已审方向686809bf与必要限量诊断，
不包含RC9、新后端行为、设备操作或配置变更。

真机证据：TITA101评论01a218d1-e2fd-7ea4-a612-1ab4752ad6e2，实装诊断包
9b863e7fcf63132ae5ad505c2be5fc63c865f2d08b31a6ff15369edd87ec8760。
flow4 consume成功→derive开始→349ms后tick撤销page→UNOWNED；3453ms后
derive成功→commit拒绝→STALE_CALLBACK。原94条枚举和原失败不修改。
此前6063e017最终诊断包也是独立旧产物，不是本修复包；不得覆盖或重命名。

修复：保存通过原前置条件后，以savingChallenge保留消费中操作的对象身份。
receipt消费仍单次；challenge=null仍然立即禁止重复消费。仅busy OWNER_PIN
的tick用ownerSaveCurrent核同page、同challenge或同saving对象、未隔离、
原expiresAt，不能把consume造成的challenge清空误判为页面失效。
worker finally清除见证。非busy/其他页面仍使用原挑战检查。

该谓词只用于UI生命周期，不能授Grant或跨IO许可；最终ParentCommit、epoch
竞争/CAS后deadline见证、owner.consume、存储原子提交/隔离完全保持。
真正到期、HOME/失焦/取消、换page、consume拒绝、写盘/密钥失败仍拒绝。
到期tick必须在worker仍阻塞时锁页，不能只是等最终提交拒绝。
已完成提交的record不会被之后tick撤销；后续仍锁定、不恢复管理授权。

版本：com.littlebuddy.sim.v2，code22，2.0.0-rc8.pin.fix1，同原RC8签名。
资源manifest16ec66f3cca282e4070481d803eb8a833f31ee6a1a7733f48bb0948329f1826e，
协议v2-voice2-safety1-images2-volume1-management1-end1，schema无变更。
普通构建诊断关闭；本候选显式-PpinInitDiagnostics=true才带诊断和fix1后缀。
此分支metadata/verifier显式--pin-init-diagnostics只接受fix1，不放宽正常RC8校验。

日志沿用专用tag V2PinInitDiag，仅固定stage/reason、进程临时flow及单调时间。
最多256条/15分钟；独立写线程，无认证线程日志IO；异常隔离。
无PIN、长度、hash、盐、nonce、signature、binding、凭据、用户文本或异常正文/stack。
成功预期SAVE_IN_PROGRESS期间不出现TICK_OWNER_INVALID，随后DERIVE/COMMIT SUCCESS，
RESULT LOCKED/PIN_CHANGED（原设计要求保存后重新验证PIN，不自动签发Grant）。

测试：原四个期望断言保持；另覆盖排队保存、consume阻塞失败、expiry等值及时锁页、
换页、取消、初始化/恢复存储失败、已提交后tick不抹记录；既有权限、最终CAS和
生产sealed存储原子性按影响回归。fixtures下原反例由脚本显式运行，不混入全套发现。

    scripts/with-build-lock python3 scripts/pin-tick-fix-tests.py

APK编译必须经scripts/with-build-lock，offline/no-daemon/max-workers=1，
-PpinInitDiagnostics=true -Pv2Test :app:assembleV2Debug（及报告中定向测试列表）。
输出app/build/outputs/apk/v2Debug/app-v2Debug.apk，root核包后才能安排安装复验。

root后续只采专用tag（作者不执行）：

    adb logcat -v raw -s V2PinInitDiag:I '*:S' > pin-fix-events.txt

复验前root确保新候选进程和采集均已就绪，避免15分钟过期要求用户重复输入。
用户暂不操作。作者不安装/ADB/云/后端/合并。原RC8同包同签code22可用于正常覆盖
回滚，保存原数据，不卸载/清数据、不使用降级或认证绕过；安装资格静态已核，
实际安装及成功复验由root统一安排。诊断可在后续普通构建关开关撤除。
