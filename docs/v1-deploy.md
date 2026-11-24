# V1 独立后端部署与回退

正式 Android 前台会话通过受限的 SSH 22 设备身份，把手机的 `127.0.0.1:19443` 转发到服务器同一回环地址和端口。业务继续使用 `wss://127.0.0.1:19443/v1/animal`、协议 v1 和同版题库。App 固定核验服务器 P-256 ECDSA 主机密钥，仅为本会话客户端信任项目 CA，同时校验标准 TLS 链、有效期及 IP SAN `127.0.0.1`。App 在 Android Keystore 中生成不可导出的 RSA-2048 签名密钥，仅使用 RSA-SHA2-256。配置页只显示可注册的公钥。独立设备令牌仍由 Keystore 加密保护并排除备份。

升级后从安装配置注册公钥并录入独立令牌。Mac 可一次性协助比对公钥指纹和注册。HTTP 401 清理旧会话并打开安全配置页，替换令牌后回待机，待手动开始状态随令牌加密保存，Activity 重建或进程冷启动后仍由照看者手动开始新会话。停止、退后台、锁屏、连接超时或断线会释放旧录放音、WSS、转发和 SSH。手机正常运行时只需自身网络和服务器。

## 准备与启用

1. 在 `/opt/little-buddy-v1/releases/<完整 SHA>` 部署获准提交和按 `backend/requirements.txt` 安装依赖的独立 `.venv`，由 root 持有且仅管理员可修改。先运行后端测试。用 `backend/deploy/select-release <SHA>` 原子更新 `current` 链接。保存上一通过验收的 SHA。切换期间只操作本实例。
2. 使用 `backend/deploy/service.env.example` 创建 `/etc/little-buddy-v1/service.env`，填写现有授权百炼项目和模型。把 API key、证书链及私钥分别配置至单元的 `LoadCredential=` 输入，凭据文件 root:root 0600、凭据目录 0700。证书必须含 IP SAN `127.0.0.1`。TLS 证书续签后重新加载凭据需要重启专用实例。启动跑在 systemd 动态非 root 用户下。
3. 在 `/etc/little-buddy-v1/` 下新建独立凭据目录（0700），其中 `token` 为 `openssl rand -hex 32` 产生的 64 个小写十六进制字符，`expiry` 为授权期限的绝对 Unix 秒。用受保护重定向写入 0600 文件，令牌只经授权私密渠道交设备操作者。由 root 创建 `device` 符号链接指向这一目录。签名流程不读取这些私密文件。
4. 把单元安装到 `/etc/systemd/system/`。运行 `systemd-analyze verify`、`systemctl daemon-reload` 和 `systemctl start little-buddy-v1.service`。从回环以严格 TLS 验证服务进程、`/healthz` 和鉴权 WSS，确认真实 UID 非 0。使用合成夹具时通过临时回环实例加 `--provider fake`，运行 `PYTHONPATH=.:backend python3 -m unittest discover -s backend/tests -q`。默认回环端口 19443，启用前核对未占用。
5. 由运维应用已独立复核且备好回退的 SSH 专用设备身份。启用前保留当前管理会话，记录管理登录与监听基线。服务端仅接受设备公钥和 RSA-SHA2-256，只允许客户端转发到 `127.0.0.1:19443`，禁用 shell、exec、子系统和其他转发。验证随后仍可新建管理连接，并从 Wi-Fi 和移动网用正式包验证业务 WSS。 [SSH 设备身份运维](device-ssh-operations.md)

单实例最多一个已升级会话。有效设备启动尝试每分钟最多 6 次，错误令牌不占设备配额。仅显式传入 `--trial-limits` 时启用每会话 ASR、LLM、TTS 次数配额和 15 分钟会话总时限。正式服务仍限制帧长、队列、握手、心跳、控制等待和单轮处理时间。公网代理还应限制未鉴权连接速率和并发。日志仅含计数、分类和时延。看护时用 `journalctl -u little-buddy-v1.service` 对照供应商计量，不记录原始音频、转写和完整聊天。合成测试核对计数与释放行为，供应商真实用量、外网时延与童声体验留最终窗口。

正式单元启用前校验 cgroup v2 的 `memory.swap.max=0`、core 软硬限制均为 0，并以合成进程确认 standalone 入口的不可转储设置。发布与回退均应配套选择含进程保护的后端和单元。若上一版本缺少所需保护，停止专用服务直至可恢复到满足条件的版本。 [隔离复验记录](bailian-data-evidence.md#专用服务隔离复验)

## 轮换、撤销和回退

- 轮换时先准备新凭据目录与期限，随后 `systemctl stop little-buddy-v1.service`，确认活动连接断开。用同一目录下临时软链接加 `mv -Tf` 原子替换 `device`，再启动专用实例。旧令牌应为 401，新令牌应成功。清理退役令牌文件。服务到期后拒绝新握手并关闭活动连接。
- 撤销时停止专用单元并解除 `device` 链接，移除原令牌。没有设备凭据时即使服务再次启动也无法接受 WSS。同时移除设备 SSH 公钥授权，精确终止该设备身份的认证中及活动连接。验证旧公钥和令牌均被拒、设备连接残留为零、管理会话和原服务健康。
- 发布回退时先停专用服务，执行 `backend/deploy/select-release <上一已验 SHA>`，启动并重复健康、严格 TLS 与鉴权检查。服务配置和当前设备凭据独立于代码版本，绝不恢复已撤销令牌。首发或没有兼容旧版本时停止专用单元、收回专用 SSH 授权。回退候选必须支持同一独立单元和协议。
- 轮换设备 SSH 密钥时先撤销或排空旧连接，重置设备安装数据会清除旧密钥和令牌。重新生成公钥后比对指纹，注册新公钥并配发新令牌。叶证书可在同一 CA 下轮换。CA 或主机密钥轮换需要协调签发新客户端，失陷时先停专用入口。
- 签名构建使用未用且大于 14 的 `-PbuddyVersionCode`、相应 `-PbuddyVersionName`、既有 `LITTLE_BUDDY_FAMILY_PROMPT` 和 `LITTLE_BUDDY_SSH_PROFILE`。SSH 配置目录只含单个项目 CA 公证书 `ca.pem` 和 `ssh.properties`，后者含固定服务器 IPv4 的 `host`、专用账号 `user` 与已核验 ECDSA SSH 公钥的 Base64 字段 `hostKey`。构建校验公钥指纹。签名前核对包名 `com.littlebuddy.sim` 与既有签名，登记 APK/签名证书 SHA-256、版本、APK 与后端提交及信任配置。设备令牌通过安装配置录入。[签名流程](build-and-release.md)
- 放行观察使用同一正式 SHA、现有供应商额度和专用非 root 实例，记录 30 分钟前台、至少两局各三题、短聊天、取消或断网后的新会话、分段延迟、请求量、CPU/RSS，以及凭据吊销和回滚结果。记录限于脱敏计数和时延。真实 OPPO 的两网连接与童声由用户在最终窗口验收。

## 正式签名包的 SSH 资产入口验收

- 以正式签名 APK 记录完整客户端与后端 SHA、版本号、APK 与签名证书 SHA-256，以及打包的 `assets/transport/ssh.properties`、`assets/transport/ca.pem` 的 SHA-256。对照构建登记核验固定 SSH 目标、已核验主机公钥与项目 CA。Android 16 的 CI 通过 debug 夹具注入 SSH 信任材料，正式签名包须单独验证 `BUDDY_SSH` 资产加载。
- 验证首装与覆盖升级后的正式配置表单只提供设备注册公钥与令牌输入，注册后走固定回环 WSS。用已授权测试设备验证一次 401 轮换，保存后重建和冷启动均保持待手动开始，手动开始后成功。最终验收记录 Wi-Fi、移动网络、错误证书或吊销凭据的拒绝和回退证据。
