已登记 OPPO 的私有连接预填候选

精确基线：已安装rc8.pin.fix2/source1ae519b16b13004a4f88418cb640df54cf72b3e1。
保留PIN修复、公钥文件入口；不引入之后未安装的导出改动、RC9或后端变更。
本次仅预填已发行的本机连接，不再做RSA/watcher/USB配置输入流程。

CONNECTION默认V2私有SSH，账户v2-device-oppo，地址
wss://127.0.0.1:19483/v2/voice。专用APK中预填已发行设备token，仍为密码控件。
只有现有PIN授权管理→系统认证→当前60秒操作挑战批准后，才显示该页面。
用户须明确点“保存已发行的连接”；不自动提交，不用预填数据充当系统认证/Grant。
busy重绘不会重新填入正在清除的凭据，原take/pending清理和最终校验不变。

通用代码不含凭据。普通构建V2_DEVICE_PRESET=false，不读资产、不打包私有输入。
仅显式-PprivateDevicePreset=true -PpinInitDiagnostics=true，输出code22/
2.0.0-rc8.pin.fix3.device1，同包同签。元数据标private_registered_device，默认
release verifier拒绝含私有预填标记/资产的包，必须显式本地private模式核验。
私有字节不进入source inventory，不写BuildConfig/源码/PR/报告或token指纹。

授权本机构建准备：

    sudo -n python3 scripts/prepare-private-device-preset.py --owner-uid <本机构建UID>

只读/etc/little-buddy-v2/v2-device-token，写.gitignore排除的
.private-device/preset.bin；目录0700/文件0600，不显示token。文件是受限私有构建输入，
不上传或提交。私有assets仅在该flag下挂载，不因旧构建缓存进入普通APK。
原账户/端点是公开的固定限制，二进制内凭据只供本次已登记手机；不做服务器登记。

重任务必须scripts/with-build-lock，内部shell先umask077，再offline/no-daemon/
max-workers1 Gradle assembleV2Debug。Gradle读取ignored私有输入复制到generated
private assets，原日志限0600；最终APK0600、父目录0700。含token APK禁止Multica
附件/公共release/公开URL分发，只沿已授权Mac设备代理现有SSH/SCP通道直接拉取。
源文件/代码/测试使用假凭据，不读真实输入。实际token一致性只作本地布尔核验，
不报告长度/值/派生token摘要，不把实际token写进错误或测试断言。

连接保存竞态：已安装源码provisionConnection消费challenge后清空它，在最终IO
完成前tick按旧挑战判断撤销page。受控commit/consume阻塞＋真实tick原失败保留。
修复沿已有savingChallenge见证，仅busy CONNECTION与OWNER_PIN使用同page/对象/
原期限/未隔离检查；finally清除。consume仍单次，原ParentCommit/CAS后期限和
存储原子性不改，真正到期/HOME/取消/换页/consume拒绝/磁盘失败仍拒绝。

    scripts/with-build-lock python3 scripts/connection-save-tests.py --original
    scripts/with-build-lock python3 scripts/device-preset-tests.py

原8条断言有3个真实竞态失败；最早harness把存储失败过早启用导致额外1个fixture
失败，单独留存，不混算生产反例。修后运行同8断言及preset/既有PIN/权限/存储回归。
不恢复旧goal、不操作手机/云/部署。root审核通用差异、私有核包后协调覆盖安装，
保留数据。私人APK路径/SHA和安全直传建议只报告给root，不作为公共附件上传。
