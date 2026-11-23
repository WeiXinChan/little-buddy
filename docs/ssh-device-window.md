# 设备专用 SSH 限时窗口

[PR #25](https://github.com/WeiXinChan/little-buddy/pull/25) 的运维入口适用于已核验的 Ubuntu OpenSSH 9.6p1 拓扑。运行中监听进程为 `/usr/sbin/sshd -D`，`SSHD_OPTS` 为空，`ssh.socket` 以 `Accept=no` 向 `ssh.service` 交接 22 的两个通配监听 FD。窗口默认 60 秒，从武装时开始计时。先让独立评审复核固定提交和演练，再按现场授权实施。

## 现场输入

- 从已认证的管理连接核对实际启动参数、Include 列表、管理账号集合、双栈监听及实际源和目标。保留一条既有管理连接并实测独立的新登录。只有确认没有漂移才沿用 TITA-64 的管理登录证据和 Mac 交接。
- 将已经核验的主配置及全部 `/etc/ssh/sshd_config.d/*.conf` 的 SHA-256 私下存成 JSON 对象。键为绝对路径。另将实际及计划使用的源/目标地址存成 JSON 数组，每项为两个数字 IP 字符串，源在前。材料放在 root 私有目录。
- 核实设备账号为专用非特权账号且未参与管理。基线不得给该账号配置其他认证路径，禁止将设备公钥放入通用授权文件。用私下核对过指纹的单行 Ed25519 公钥。设备私钥留在客户端。
- 事先验证受控健康服务只绑定 `127.0.0.1:24457`，并通过现有私密交接核对 SSH host key、TLS CA、SAN 和 HTTP 健康判据。SSH Match 限制连接目标，TLS 校验由客户端执行。
- 窗口期间停下 SSH 配置管理和其他 SSH 重载操作。此入口假设正常运行、磁盘配置可写、journald 可读、PID 及配置基线稳定。配置文件使用 Ubuntu 默认元数据，无额外 ACL 或扩展属性。复核站点单元和生效 drop-in，确保与验臂检查一致。

## 预备、武装及开启

在已核对提交 SHA 的目录执行。单元和脚本文件的 SHA-256 随固定提交一起核对。

```bash
sudo install -D -m 0755 scripts/ssh-window/window.py /usr/local/libexec/tita-ssh-window.py
sudo install -m 0644 scripts/ssh-window/tita-ssh-window.{timer,service} /etc/systemd/system/
sudo systemctl daemon-reload
sudo /usr/bin/python3 -I /usr/local/libexec/tita-ssh-window.py prepare \
  "$DEVICE_USER" "$PUBLIC_KEY" "$CONTEXTS_JSON" "$HASH_MANIFEST_JSON"

sudo systemctl start tita-ssh-window.timer
sudo /usr/bin/python3 -I /usr/local/libexec/tita-ssh-window.py verify-arm
sudo /usr/bin/python3 -I /usr/local/libexec/tita-ssh-window.py open
```

`prepare` 验证配置散列、双栈继承、两个版本的语法及全部非设备 NSS 账号在代表性和现场条件下的生效配置，并将备份及输入写入 `/run/tita-ssh-window/private`。它使用 NSS 枚举结果，不直接读取或复制认证数据库文件。它在设备 Match 中禁用用户 CA 证书及命令取钥，并将可接受算法限制为普通 Ed25519。服务端只在候选重载及再次验臂成功后发布专用公钥。单元由系统管理器启动，发起 SSH 会话退出时仍能执行。

把实际截止和私密材料位置交给外测协调方。若开启任一步失败，保留定时器并从保留的管理连接立即启动回滚服务。

## 回滚与清理

等待 timer 到期或提前执行 `sudo systemctl start --no-block tita-ssh-window.service`。回滚独立于开窗锁。服务先写下回滚墓碑，再移除本代际暂存公钥和已发布公钥。随后移除本代际暂存配置，按备份散列原子恢复配置并重读 `ssh.service`。重载由 journal 中的 SIGHUP 及两条监听记录确认，同时复核主进程及两个继承 FD。排空只向仍符合监听父进程、启动时间、设备身份标题和服务端连接归属的 pidfd 发送 TERM。未知身份等待 120 秒认证宽限。每次预备生成唯一代际。开窗只能原子移动该代际的暂存文件，恢复执行的旧进程无法重建被移除的源文件。135 秒截止时仍有设备或未分类连接，返回 42 并保留残留数量。systemd 回滚运行上限为 155 秒。

```bash
sudo systemctl show tita-ssh-window.service -p Result -p ExecMainStatus
sudo journalctl -b -u tita-ssh-window.service --no-pager
sudo /usr/sbin/sshd -t
sudo systemctl show ssh.socket -p ActiveState -p Listen
```

退出 0 后，核对主配置和 Include 散列、既有和独立新管理登录、双栈监听、设备新认证被拒及既有设备传输关闭。退出 42、其他非零或 systemd 超时均判窗口失败。保留私有证据和备份，从管理连接核对授权文件已撤、实际配置及残留。遇配置漂移时，保留新的配置字节与备份供人工比对。仅在复核恢复状态后清理。先停 timer 并确认回滚服务及开窗进程已退出。确认本代际在 `/etc/ssh/.tita-ssh-window-<generation>.next` 的暂存文件已回收，再移除专用状态目录、安装的脚本和单元，执行 `systemctl daemon-reload`，回收独立的健康服务。

## 隔离演练

在匹配的 Ubuntu 上串行运行。

```bash
sudo scripts/ssh-window/rehearse normal
sudo scripts/ssh-window/rehearse timeout
```

每条路径使用有硬时限的独立 mount、network、PID 和 cgroup namespace，在其中启动 systemd 并使用发行版实际的 `ssh.service` 和 `ssh.socket`。SSH 配置、账号、公钥和 TLS 服务均为合成材料。外层对照宿主配置散列和生产监听 socket。时序检查涵盖发起会话退出、已登录设备、暂停签名的认证请求及尚未声明身份的连接。超时路径在开始排空 25 秒后建立一条未知连接，在 135 秒截止时验证它仍存活。测试仅在验证单元实际返回 42 且其它断言通过时视该超时用例为成功。

锁停滞回归使用同一 timer 和 service。下列两条路径分别在公钥发布后和发布前的原子移动边界暂停持锁开窗进程。演练验证回滚完成、随后恢复原进程仍无法发布、既有和独立新管理登录可用。

```bash
sudo scripts/ssh-window/rehearse stalled-published
sudo scripts/ssh-window/rehearse stalled-publish
```

## Mac 提前准备

沿用已核验的私密材料。Mac 按目标地址将已有 host key 写入单独的 known_hosts，保留既有 CA PEM、证书 DNS SAN 和设备私钥。材料通过既有私密交接流转。健康检查使用已核的 HTTPS 根路径和 HTTP 200 判据。脚本默认用本机回环端口 24561，遇占用会拒绝建立转发。设备私钥若有口令，运行前由 Mac 用户加载到本机 SSH agent。

```bash
scripts/ssh-window/mac-health preflight "$SSH_HOST" "$DEVICE_USER" \
  "$DEVICE_IDENTITY" "$KNOWN_HOSTS" "$TLS_CA" "$TLS_NAME"
scripts/ssh-window/mac-health probe "$SSH_HOST" "$DEVICE_USER" \
  "$DEVICE_IDENTITY" "$KNOWN_HOSTS" "$TLS_CA" "$TLS_NAME"
```

`preflight` 只检查本地文件。协调方给出实际开窗和截止后才执行 `probe`，只汇报 UTC 时间、结果和网络路径。

如需给 Mac 留出切换网络路径的时间，建议评审固定 300 秒，从武装开始计时。600 秒作为可评审的硬上限，超过即拒绝武装。300 秒和 600 秒的配置计时预算分别为武装后 455 秒和 755 秒，另计 timer 的 1 秒调度精度，现场仍以实际验臂记录为准。该评估沿用 135 秒排空截止和 155 秒单元运行上限。若采纳，timer 与验臂必须使用同一审定值，并重验计时和逾期拒绝发布。本提交仍使用 60 秒窗口。
