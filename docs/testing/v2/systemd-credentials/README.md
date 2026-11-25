Systemd真实只读凭据兼容：只限定系统服务挂载

基线ba7ad42596feb315cddb910d15baa53d0956f1e8。root报告真实V2启动失败service_env_invalid，且已停止V2，V1未动；本批没有重试生产启动或读取生产日志/凭据。之前普通临时目录chmod400预检绿只能证明普通私有文件路径，不证明实际LoadCredential可读。本目录保留旧源码在真实合成namespace下的拒绝原件及修复后的成功原件，原部署阶段绿证据不删除。

设计边界

普通secret读取仍要求自有/root所有者、真实regular单硬链、有界大小、叶/直属父目录O_NOFOLLOW。普通secret父目录现在也拒绝全部group/other权限，源目录0700、源文件0600保持；0400/0500私有只读普通文件仍可读。公开证书secret=False的原非可写模式规则保持。deployment.checked_image_sources原严格0600源检查未改。

仅当普通模式检查原本会因group位拒绝时，files.py新增下列同时成立的例外：

1. 非root执行，绝对路径的直属父目录精确等于CREDENTIALS_DIRECTORY，且只能是本V2部署使用的系统服务路径/run/credentials/<受限ASCII名称>.service。环境变量只提供待验候选，不提供授权；不支持任意环境路径、用户manager或其他部署路径的自动回退。
2. 打开的父目录root:root精确0550、文件root:root精确0440，仍须regular/nlink1/大小上限；真实gid0不要求等于动态egid。没有推断或伪造ACL。
3. 从/run开始通过O_DIRECTORY|O_NOFOLLOW锚定走到credentials和该service；每一级root所有、非group/other可写，最终锚定FD的dev/inode等于最初打开父目录FD，防止仅凭可替换路径自证。
4. /proc/self/fdinfo的mnt_id必须在锚定目录、原目录和文件三个FD间相同。三个FD的fstatvfs均须ST_RDONLY。
5. /proc/self/mountinfo须有该同一mount ID，mountpoint精确等于已核候选路径、挂载选项有ro、文件系统为tmpfs或ramfs。可写文件系统、仅普通子目录、不匹配/不可读的proc元数据都拒绝，不能只靠环境变量、ismount或路径字符串。

不扩大到/etc或普通0440目录，不把组可读当普遍许可。持有经过核验的目录/文件FD继续读，原读前后大小/mtime/ctime稳定性检查保留。没有持授权锁跨IO、没有修改业务权限/协议/模型/适配器。可信root和kernel仍是边界；这不是对恶意root的密码学systemd发行者证明。

[systemd官方凭据语义](https://www.freedesktop.org/software/systemd/man/256/systemd.exec.html)说明凭据位于受控只读位置并导出CREDENTIALS_DIRECTORY；[官方Credentials说明](https://systemd.io/CREDENTIALS/)列出系统服务路径。当前部署是系统manager；对其他路径/文件系统/模式组合失败关闭，不以任意环境变量放宽。

真实合成验证

已获授权，sudo -n可用。执行`python3 tests/v2/systemd_credential_probe.py`前台等待两个唯一wali-credential-*临时单元：DynamicUser=yes、LoadCredential(module.py与随机合成fixture)、ProtectSystem=strict、ProtectHome=yes、PrivateTmp=yes、RuntimeMaxSec=15、--wait/--pipe/--collect。不引用任何生产unit或实际凭据，不启停V1/V2；临时服务和临时UID属于测试，不创建持久账号。

original-namespace.json：旧基线代码exit23，synthetic_file_invalid。fixed-namespace.json：新代码exit0、accepted。同类实际元数据均为非root euid/egid、parent root:root0550、file root:root0440、nlink1、非symlink、真实mountpoint、ST_RDONLY=true；动态egid不是0。源材料随机、从不打印/散列输出内容，只输出metadata/固定码。两个单元均已退出并collect；不是生产preflight或上线验收。

新增8项最小边界测试通过，另2项直接受影响的既有临时联合预检/源与credential模式检查通过，总10/10、0失败/错误/跳过；普通groupread、假环境、可写FS、不同FD挂载ID、叶/父symlink/硬链、坏root模式/gid及缺proc均拒绝。可写FS/FD身份门的隔离单元测试明确使用受控metadata桩来抵达相应门，不把桩当真实RO成功；RO成功仅由上述真实systemd证据证明。没有重跑旧业务/模型集合。

root后续操作：审合本PR后，从固定新main构建并核独立发行包，按既有受控配置做真实离线check和生产systemd启动复核。此次没有部署、启停生产服务、云调用、设备或APK构建；不能据合成namespace成功冒称生产启动已恢复。
