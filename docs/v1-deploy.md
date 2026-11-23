# V1 独立后端部署与回退

软件基线是 PR #22 合入后的 `ce79deb94b5b63d774609726f2970981f317c052`。正式 Android 使用 `wss://<目标>/v1/animal`、协议 v1 和双方代码声明的同版题库。首装在配置页输入经验证的完整 WSS 地址及单设备令牌。令牌由 Android Keystore 保护且文件排除备份。令牌替换后，客户端收到 HTTP 401 会打开安全配置页并保留服务地址，重新配置后可发起新会话。断线、TLS 失败及其他连接失败会清理录放音和会话，恢复网络后点开始。后台无自动重连。

正式包沿用平台信任链和主机/IP 校验。公网仍需确认云防火墙、现有接入约束、外网 TLS/WSS 与证书续签后重启。TITA-54 的 443 外测未拿到叶证书或 HTTP 响应。独立项目 CA 和 SSH 22 原型由协调方另行评审，当前正式构建使用系统信任。回环验证通过后，仍需在 Wi-Fi 和移动网使用最终签名 OPPO 包验证，无需 Mac、USB 或 SSH 常开。

## 准备与启用

1. 在 `/opt/little-buddy-v1/releases/<完整 SHA>` 部署获准提交和按 `backend/requirements.txt` 安装依赖的独立 `.venv`，由 root 持有且仅管理员可修改。先运行后端测试。用 `backend/deploy/select-release <SHA>` 原子更新 `current` 链接。保存上一通过验收的 SHA。切换期间只操作本实例。
2. 使用 `backend/deploy/service.env.example` 创建 `/etc/little-buddy-v1/service.env`，填写现有授权百炼项目和模型。把 API key、证书链及私钥分别配置至单元的 `LoadCredential=` 输入，凭据文件 root:root 0600、凭据目录 0700。证书必须覆盖客户端实际填写的主机或 IP。TLS 证书续签后重新加载凭据需要重启专用实例。启动跑在 systemd 动态非 root 用户下。
3. 在 `/etc/little-buddy-v1/` 下新建独立凭据目录（0700），其中 `token` 为 `openssl rand -hex 32` 产生的 64 个小写十六进制字符，`expiry` 为授权期限的绝对 Unix 秒。用受保护重定向写入 0600 文件，令牌只经授权私密渠道交设备操作者。由 root 创建 `device` 符号链接指向这一目录。签名流程不读取这些私密文件。
4. 把单元安装到 `/etc/systemd/system/`。运行 `systemd-analyze verify`、`systemctl daemon-reload` 和 `systemctl start little-buddy-v1.service`。从回环以严格 TLS 验证服务进程、`/healthz` 和鉴权 WSS，确认真实 UID 非 0。使用合成夹具时通过临时回环实例加 `--provider fake`，运行 `PYTHONPATH=.:backend python3 -m unittest discover -s backend/tests -q`。默认回环端口 19443，启用前核对未占用。
5. 只有入口条件已验证时才配置独立可回退的路由。反向代理仅转发精确 `/v1/animal` 的 WebSocket Upgrade，传递匹配的 Host、单值 Authorization，验证代理到回环的 TLS 身份，并拦住 `/healthz`。若经批准由专用实例直接监听标准 443，先核实监听及防火墙，`LITTLE_BUDDY_AUTHORITY` 设置为客户端目标 IP 或域名，省略 `:443`。上生产前记录可逆变更清单和具体回滚指令，核对原 80/8443/8444/9444 的业务基线。以外网实际握手验证证书链、目标 SAN、无效令牌与正确令牌，记录脱敏验证结果。

单实例最多一个已升级会话。有效设备启动尝试每分钟最多 6 次，错误令牌不占设备配额。应用会话限制 ASR、LLM 和 TTS 次数，另有帧长、队列、心跳和时限。公网代理还应限制未鉴权连接速率和并发。日志仅含计数、分类和时延。看护时用 `journalctl -u little-buddy-v1.service` 对照供应商计量，不记录原始音频、转写和完整聊天。合成测试核对计数与释放行为，供应商真实用量、外网时延与童声体验留最终窗口。

正式单元启用前校验 cgroup v2 的 `memory.swap.max=0`、core 软硬限制均为 0，并以合成进程确认 standalone 入口的不可转储设置。发布与回退均应配套选择含进程保护的后端和单元。若上一版本缺少所需保护，停止专用服务直至可恢复到满足条件的版本。 [隔离复验记录](bailian-data-evidence.md#专用服务隔离复验)

## 轮换、撤销和回退

- 轮换时先准备新凭据目录与期限，随后 `systemctl stop little-buddy-v1.service`，确认活动连接断开。用同一目录下临时软链接加 `mv -Tf` 原子替换 `device`，再启动专用实例。旧令牌应为 401，新令牌应成功。清理退役令牌文件。服务到期后拒绝新握手并关闭活动连接。
- 撤销时停止专用单元并解除 `device` 链接，移除原令牌。没有设备凭据时即使服务再次启动也无法接受 WSS。必要时再关闭专用公网路由。确认端口及原服务健康状态。
- 发布回退时先停专用服务，执行 `backend/deploy/select-release <上一已验 SHA>`，启动并重复健康、严格 TLS 与鉴权检查。服务配置和当前设备凭据独立于代码版本，绝不恢复已撤销令牌。首发或没有兼容旧版本时停止专用单元、收回专用路由。回退候选必须支持同一独立单元和协议。
- 签名构建传入 `-PbuddyVersionCode=<本升级线已登记的递增整数>` 及 `-PbuddyVersionName=1.0.0`，和现有 `LITTLE_BUDDY_FAMILY_PROMPT` 私有输入一起执行 `:app:assembleRelease`。签名时核对包名 `com.littlebuddy.sim` 与既有证书，登记 APK、证书 SHA-256、版本号、APK 与后端完整提交及信任配置。服务地址和设备令牌由运行时配置，构建日志只留非秘密版本元数据。[签名流程](build-and-release.md)
