V2 图片/反馈部署输入接线（未部署）

基线main fd98c722e4896ffe953840951f19456c76f46a33，包含已合PR64–67，文本/图审固定deepseek-v4.1-flash-1017，禁止旧Qwen文本回退。本批仅部署模板/控制脚本、定向检查与说明；不改Android、协议、VoicePeer、供应商适配器、V1或实际受控输入。

默认 unit 的离线check与正式start参数除--check外完全一致：--image-config %d/image.json、--feedback-database %S/little-buddy-v2/feedback/issues.sqlite、--credential-directory %d、回环19483及原精确APK契约。LoadCredential三个图片ID为image.json、dashscope-image-key、dashscope-review-key，源均为/etc/little-buddy-v2下同名文件，与image_runtime读取名完全一致。无环境明文key或自动借用V1凭据。

root源仍要求专属目录0700、文件root0600；v2-control额外用lstat/所有者/单硬链/模式核三个图片源的元数据，不读/输出内容，即使image.json显式disabled也与LoadCredential的必需文件要求一致。systemd为DynamicUser提供只读credential副本；live原checked_file允许其0400/私有父目录，不把源0600放宽成全员可读。

反馈状态使用StateDirectory=little-buddy-v2、StateDirectoryMode=0700，ProtectSystem=strict和DynamicUser保留。直属feedback子目录由启动时ExecStartPre=/usr/bin/install -d -m0700 %S/little-buddy-v2/feedback准备；它在源码release verify之后、live --check之前执行，仅建目录、不建库。SQLite仅在正式serve时由现有FeedbackStore创建/打开。未额外授予V1或其他用户写权限，未增加公开监听、代理、备份或导出。

DynamicUser的StateDirectory可通过/var/lib/private和符号链接呈现；反馈库直属父目录因此选真实feedback子目录，不能直接把StateDirectory顶层别名作为checked_runtime的父目录。本地临时测试模拟了祖先链接＋真实子目录可接受、直属父目录链接拒绝；不是实际systemd mount/id-map/UID迁移证明。[systemd官方StateDirectory/DynamicUser语义](https://www.freedesktop.org/software/systemd/man/256/systemd.exec.html)。

root预检与首装

v2-control.py check SHA默认仍只报plan，不读输入。check SHA --apply才做源码release verify、三个图片源元数据验证及完整live --check，带相同图片/反馈输入但不创建库、不创建state父目录、不切current、不执行systemctl。start/rollback --apply也先用相同checked_release，再停止/切换/启动本V2单元；失败保留原有failed_closed码，不自动恢复旧凭据。

首装必须由root在审定部署时先准备父目录，否则root预检按设计拒绝而不暗中创建。仅对**尚未使用、无已有材料的首次安装**，root可先执行：

```sh
install -d -o root -g root -m 0700 /var/lib/little-buddy-v2 /var/lib/little-buddy-v2/feedback
```

不要在已受systemd DynamicUser/id-map管理的既有目录上反复root chown。systemd启动时管理StateDirectory的私有存储/所有者迁移，feedback子目录由服务UID的install准备；已有目录需要root先核实际所有者、0700和状态迁移，不猜动态UID。预检不验证该未来UID实际可写性，真实service namespace和打开库仍需root启动后核实。

其余root实际步骤：从最终已审SHA生成/校验新发行包、准备既有wheelhouse venv及release-manifest；保留原受控/etc目录权限和精确模型输入；安装审定unit并在目标机核实systemd版本/语法、daemon-reload；先check SHA --apply，再按既有授权start SHA --apply并核ready/私有反馈库0600、两项功能启用及实际关闭/重启持久性。这些操作本批均未执行；启动/云权限/费用/真机不是临时预检的证明。

默认**不传**--feedback-copies-policy，也不设置single-store-no-exports-v1。联合临时预检得到feedback.copies_reviewed=false；未经root核对真实备份/导出/日志/所有副本，不得据单库删除返回all_copies_deleted=true。StateDirectory存在或源码不导出均不能代替实际副本核实。

实测范围

8项新增定向检查，原功能/全集不重跑：实际systemd-analyze 255 verify exit0；临时unit仅替换python可执行、WorkingDirectory与credential源路径为临时fixture，不安装/启动单元。真实控制checked_release的两条Python子进程分别通过release verify与live --check（临时自签TLS/合成token和key/精确DeepSeek/image配置）。图片为configured_not_cloud_verified，反馈为self_hosted_configured_not_accepted，copies_reviewed=false，无数据库创建。错误配置、权限、缺父目录、源与credential副本模式、同参数保证及无systemctl边界均检查。资源只用临时合成材料；未读真实凭据、创建系统目录/账号或争用heavy锁。
