RC8技术故障循环定位与最小止环

基线fix3 c7c68bb7844c7ddff05bd275c6d59e699a654ad8，保留私有内置配置、PIN和
连接保存修复、公钥导出，不引入RC9，不要求用户重新输入配置。

源码确认环路：VoiceClient一般失败/Capture失败→showLocalHelp→安全帮助页
“回到眼睛”/返回→resumeConfigured→重建连接/捕获→同故障再次help。
原多个技术失败和受scope约束的真正local_help共用同UI。不是已证实网络根因。
root服务器事实：复现时SSH Accepted publickey且指纹匹配后session closed，
V2服务active；只能证明SSH公钥认证，并不证明转发/TLS/WSS/协议/捕获成功。

修复分流：仅经过LocalHelpScope接受的安全帮助和明确本地帮助入口保留原帮助。
一般失败→固定技术阶段→停止音频/传输→眼睛故障反馈，保留隐藏家长入口。
RuntimeRetryGate跨onResume/focus/help返回禁止自动重连；只显式退出家长管理
开放一次尝试。原安全帮助文案/离线TTS/作用域门不改。失败释放不确认仍隔离，
不恢复上传；本地家长管理不需录音，可在音频隔离时进入，退出也不放行未释放资源。
不更改录音阈值/ledger/buffer/TLS/hostkey/权限/token。

误导状态：成功保存当前页通知host“本机配置已保存、尚未核验”，在锁定页重绘
前更新；异步读到真实配置也先更新notice再启动。旧callback不更新新页。
“已保存”不等于“服务已连接”，正常thinking/waiting不再误报连接不可用。

诊断复用V2PinInitDiag固定枚举、进程临时flow与单调时间，256条/15分钟，
私有候选开关启用，onCreate即启用。记录CONFIG、SSH成功、FORWARD、SOCKET、
WSS升级/HTTP鉴权安全枚举、PROTOCOL、CAPTURE native/model/startup/queue/
clock/KWS、技术hold和help。异常仅固定白名单TLS/SSH/超时/IO/安全/状态等分类，
不读message/stack，不输出token/URL/原始帧/识别内容/HTTP正文。
这些阶段用于拿第一次真实失败证据，不把猜测当具体根因修复。

root下次应先开始专用tag采集，再启动新候选，避免缺首阶段或15分钟到期；
新包启动只自动尝试一次，失败停眼睛；用户无需重复输入配置。
    adb logcat -v raw -s V2PinInitDiag:I '*:S' > runtime-stage-enums.txt
此命令仅给root设备代理，作者不执行ADB或联系设备。

定向测试：scripts/with-build-lock python3 scripts/runtime-retry-tests.py。
保留现有PIN/连接/期限/存储安全，新增技术hold/显式重试、安全scope及保存通知。
私有候选code22/2.0.0-rc8.pin.fix4.device1，同签，仅受限文件直传，禁止APK附件。
