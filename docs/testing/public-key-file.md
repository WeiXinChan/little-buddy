V2公钥文件导出（RC8 pin.fix2）

基线为实装且已真机验证PIN初始化/验证/退出再验证成功的
46cddced07e2e63b0a67bfe32ef840364c7fcdd6；不回退fix1，不合入RC9/后端更改。
本次只解决手机不便打开聊天、需通过USB把公钥传到Mac的阻断。

用户入口（root核包/安装后再协调用户）：
长按原隐藏管理入口 → PIN验证 → 家长管理 →
“保存V2公钥文件（USB传到Mac）”。现有“导出V2设备SSH公钥”分享按钮原样保留。

Android10/API29以上：直接保存到共享Download（文件管理器通常显示“下载”）。
请求文件名 wali-v2-device.pub；若已有同名文件，系统可分配带序号的新.pub名，
不覆盖旧文件。成功Toast显示实际Download/文件名；USB文件传输可复制到Mac。
没有剪贴板、公钥日志、自动服务器注册/上传，也不导出私钥、PIN或token。
文件严格为单行“ssh-rsa BASE64”加换行，不含注释或其他字段。

Android8–9/API26–28：使用系统“另存为”，建议选择设备本地Download目录；
仅传文件名/本地选择要求，不向Intent传公钥正文。ACTION_CREATE_DOCUMENT结果
完成后只继续已释放的公钥文件流程，原管理Grant仍按失焦/pause撤销，不恢复授权。
不申请全盘存储、传统读写存储、安装等新权限。只写新建空文档；非空/未知大小
文档拒绝，不删除其中已有内容。不持有持久URI权限。

实际生产链：ParentPanelView按钮 → Activity持有的AndroidPublicKeyFile.begin →
model.exportTransportKey（失败回调仅文件路径使用，分享旧签名不变） → 原V2SshIdentity.load(create=true).registrationKey() →
原最终d.acceptProtected(current)/当前页面检查 → 仅公钥release → 文件IO worker。
现有alias复用；只有原授权路径首次没有key才允许既有load逻辑创建，不改/替换key。
文件类没有ParentDomain、Grant、PrivateKey、PIN或连接凭据字段。
最终门是原模型将公钥发布给当前UI的显式公开边界；不把Boolean作为跨IO授权。
系统文件选择器之后保留的是这份已公开的payload，不是管理能力。

MediaStore.Downloads：只insert本次新行，IS_PENDING=1，写入/关闭/有界逐字节
读回核对后，确认实际.pub名，才设IS_PENDING=0。任何失败/取消清理仅新行。
不按名称查找覆盖任何现有文件。若取消与publish竞争，取消在本地完成决定前
获胜则删除新对象；已完整提交的公开文件保留。provider IO不持授权锁/缓存monitor。
不能保证物理打断卡住的系统provider；未完成不报成功，当前写入未退出不允许新写。
清理失败明确提示未确认并阻止当前实例进一步创建，不假装删除。

一次只允许一个请求，重复点击不再读取key或创建行；未完成请求最多120秒，
失焦/HOME/离开管理取消直接下载，旧回调/到期不发布新文件。picker预期失焦仅保留
已公开payload；取消选择/超时/销毁会清除缓存，返回的空新文档执行清理。
进程被系统直接终止时不承诺finally执行；MediaStore pending对象由系统规则处理，
并未把这类情况说成保存成功。正常取消/异常清理由受控回归覆盖，真实provider待复验。

检查：scripts/with-build-lock python3 scripts/public-key-file-tests.py
20项可运行检查使用真实ParentPanelModel/ParentDomain最终门和生产文件核心，
含public-only序列化、失败/取消/发布竞争/清理失败、旧页/过期，非源码字符串断言。
Android编译与原PIN回归按报告提供；不是手机导出/USB/Mac已验证。

构建：既有SDK/缓存，同签名code22，-PpinInitDiagnostics=true生成
2.0.0-rc8.pin.fix2；scripts/with-build-lock、offline/no-daemon/max-workers1。
原资源manifest16ec66f3...、协议不变。产物只交root，不作者安装/ADB/云/注册/部署。

参考：
https://developer.android.com/training/data-storage/shared/media
https://developer.android.com/training/data-storage/shared/documents-files
https://android.googlesource.com/platform/packages/providers/MediaProvider/+/8e3c6bd122b2e42fd4a35659438060caa5448784/src/com/android/providers/media/util/FileUtils.java
这些说明API29+自有Downloads无需存储权限、系统新建文档和文件名去重；不代表
OPPO/USB实测。MIME使用application/octet-stream保留.pub，实际名仍在发布前核验。
