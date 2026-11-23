# 正式 SSH 设备身份运维

TITA-76 为家庭 Release 提供一个长期、单设备 SSH 授权槽。TITA-74 签后 APK 的 `assets/transport/ssh.properties` 使用 `little-buddy-device`。复用同一服务器地址、SSH 22、已钉扎的 ECDSA P-256 主机公钥和项目 CA。设备 SSH 公钥和后端设备令牌分别授权。

独立审查通过后，才可按发布安排在正式服务器执行安装或注册。安装前确认 TITA-73 的观察已结束，并确定有独立管理入口和回退权限。

## 安装前核验

- 固定并登记 Git 提交、以下三个文件的 SHA-256、OpenSSH 包版本、主配置及所有 Include 文件的 SHA-256。复核启动参数、PAM、管理来源和监听拓扑。下方流程对应 Ubuntu OpenSSH 9.6p1、`ssh.socket` 监听 22、`ssh.service` 提供管理访问的现有环境。OpenSSH 升级或监听拓扑变化后重跑隔离验证。
- 用签后 APK 的公开资产核对 `user`、主机地址、主机公钥和项目 CA。用已信任的管理连接核对服务器 ECDSA 公钥。保留活跃管理会话，记录监听、主 PID 和新管理连接的行为。
- 检查 `00-little-buddy-device.conf` 在现有通配 Include 中的排序，检查是否存在优先生效的设备 Match、其他密钥来源或外部 PAM 身份源。候选配置须通过下面的 `check`。Match 作用域限定设备账号，末尾以 `Match all` 收束。对于局部地址条件，为每个实际管理来源和服务器监听地址传入 `PEER,LOCAL`，IPv6 同样适用。
- TITA-68 的开窗脚本及服务、定时器以单次回退为目的。持续运维由本仓库的 `device-ssh` 和设备 Match 配置提供。

在独立审查批准的固定源码检出目录中执行以下准备命令。已有同名账号、状态目录或配置文件时，先检查归属和授权，交由运维处理冲突。

```sh
sudo install -D -o root -g root -m 0755 backend/deploy/device-ssh /usr/local/libexec/little-buddy-device-ssh
sudo install -d -o root -g root -m 0755 /etc/little-buddy-ssh /etc/little-buddy-ssh/home
sudo useradd --system --user-group --no-create-home \
  --home-dir /etc/little-buddy-ssh/home --shell /usr/sbin/nologin little-buddy-device
sudo passwd --lock little-buddy-device
```

为安装及回退使用两个完整配置快照。先将 SSH 主配置及 Include 拷贝到仅 root 可写的暂存目录，将副本里的 Include 路径指向暂存副本。基线保留现有 Include 集合，候选快照添加本仓库的 Match 文件，保持最终文件名和排序。运行下列核验，参数为快照文件和实际源、目的地址对。

```sh
sudo /usr/local/libexec/little-buddy-device-ssh check baseline.conf candidate.conf PEER,LOCAL
```

检查成功后重新确认生产配置哈希与基线一致。将设备 Match 以 root:root 0644 安装在 `/etc/ssh/sshd_config.d/00-little-buddy-device.conf`。以真实 Include 运行 `sshd -t` 和同一矩阵，随后 `systemctl reload ssh.service`。检查原管理会话、新管理登录、服务主 PID 和监听端口。槽位空时设备登录应失败。检查失败时保持旧管理会话，移除本次加入的 Match 文件，验证基线并 reload。设备公钥发布只在这些检查通过后进行。

## 注册、撤销、回退

- 登记设备实际生成的单个 RSA-2048 公钥。从可信交接渠道与照看者比对 `ssh-keygen -lf 公钥文件` 的 SHA-256 指纹。由 root 执行 `/usr/local/libexec/little-buddy-device-ssh register 公钥文件`。已登记同一指纹可重复运行，换钥须先撤销。确认 App 正常建立严格 SSH/TLS 后，独立配发后端令牌。
- 撤销时运行 `/usr/local/libexec/little-buddy-device-ssh revoke SHA256:指纹`。先删除授权并同步到磁盘，再用 Linux pidfd 对专用 UID 的 worker 和该账号的 OpenSSH 特权监控进程做服务器端排空。撤销等待登录宽限期覆盖已开始的握手。无法判定目标用户名的握手继续由原 SSH 守护进程处理。当前生产宽限期 120 秒，整次撤销约需两分钟。失败时保留拒绝授权状态，按同一指纹重试并核对结果。同步独立撤销后端令牌，验证旧密钥和旧令牌均被拒。
- 回退时执行 `/usr/local/libexec/little-buddy-device-ssh rollback`，无条件清空槽位并排空设备连接。成功后可保留空槽作为默认拒绝状态。若要恢复基线 SSH 配置，先撤销后端令牌，再只移除该 Match 文件，经 `sshd -t` 核验后 reload。检查设备登录拒绝、管理连接和现有服务健康，保留锁定账号和审计记录。恢复后重新比对配置哈希，经过批准后才可重新注册。避免回放历史授权文件。
- 在正常运行的 SSH 服务上执行排空。审查期间保持 SSH 二进制版本、账号 UID 与登录宽限期稳定。该 UID 专用于设备 SSH，不运行其他业务或任务。对比主机日志中的连接和排空完成记录，遇到进程识别失败时先保留拒绝授权状态，再按变更记录调查。
- 持久状态在 `/etc/little-buddy-ssh`，目录及空 home 为 root:root 0755。SSH 降权后可读取公钥，语音服务的私有配置目录继续使用原权限。授权文件为 root:root 0644，公钥条目同时限制 `permitopen`。审计日志和互斥锁为 root:root 0600。审计记录 UTC 时间、动作和公钥指纹。注册以文件和目录同步及原子替换完成，管理员只可通过受控入口变更该目录。

## 隔离复核

在安装了 OpenSSH、OpenSSL 和 iproute2 的 Ubuntu 主机，以同一固定提交执行。夹具需要 OverlayFS 和空闲的 `/etc/little-buddy-ssh` 路径。在私有 PID、网络和挂载命名空间使用仅回环网络、合成账号、合成主机与设备密钥、合成证书及独立状态。检查输出中的各项结果和文件哈希。

```sh
sudo unshare --mount --net --pid --fork --mount-proc backend/deploy/test-device-ssh
```

该夹具实际停止并重新启动隔离 sshd，复用同一授权文件，并在撤销后切换回基线重启。它覆盖服务进程替换和持久文件读取。正式系统重启、正式 SSH reload、正式流量和 OPPO 均需单独验收。

[OpenSSH 服务端配置手册](https://man.openbsd.org/sshd_config) · [OpenSSH 守护进程手册](https://man.openbsd.org/sshd.8)
