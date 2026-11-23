# TITA-62 现网 SSH 22 设备 Match 离线复核

**结论。** 本机配置副本的生效参数比对通过。回环夹具验证了设备转发约束、配置恢复及已知连接的精确终止。外测仍须独立复核，并由协调方确认现网 socket 激活方式下的回滚和设备连接定位。当前没有启用现网试验。

## 输入与边界

- TITA-59 在固定提交 `7d4bb0bc4e92b4e4b46f56f0eea857521c3ceafb` 复跑了 14 项回环检查。[PR #24](https://github.com/WeiXinChan/little-buddy/pull/24)
- TITA-60/TITA-61 的 Mac Wi‑Fi `en0` 路径到独立 TCP 2222 单次超时，默认 `utun6` 路径完成 TCP 握手。协调方关闭并回收独立监听。随后 `en0` 和 `utun6` 各读取一次现网 TCP 22 的预认证 banner。设备公钥认证、应用层 TLS/HTTP 和 OPPO 路径均无外部实测结果。
- 验证运行在当前服务器的 OpenSSH 9.6p1 Ubuntu 包上。先把主配置和 Include 目录复制到私有临时目录，在独立 mount namespace 中将副本绑定为 `/etc/ssh`。原来的绝对 Include、glob 和排序保持原样。本次盘点有一份 Include 文件，基线无现有 Match。副本和夹具仅使用临时 host key，未复制现网私钥或授权密钥。现网 `ssh.socket` 处于 active 状态。动态夹具则在 net/PID namespace 中独立监听 loopback 22，并用临时管理身份材料、临时设备账号和合成 TLS 后端。

## 候选差异

主配置基线字节保持原样，在全部原有内容之后追加下列块。实际设备用户名、授权公钥文件及期限由获准窗口单独配置。本次使用固定回环目标 `127.0.0.1:24457`。

```sshconfig
Match User <DEVICE_USER>
    AuthenticationMethods publickey
    PubkeyAuthentication yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    HostbasedAuthentication no
    GSSAPIAuthentication no
    AuthorizedKeysFile <DEVICE_AUTHORIZED_KEYS_FILE>
    AuthorizedKeysCommand none
    MaxSessions 0
    PermitTTY no
    AllowAgentForwarding no
    X11Forwarding no
    AllowTcpForwarding local
    PermitOpen 127.0.0.1:24457
    PermitListen none
    AllowStreamLocalForwarding no
    PermitTunnel no
    PermitUserRC no
```

`MaxSessions 0` 拒绝 session channel，因此设备仍能使用 `ssh -N`，无法打开 shell、exec 或 subsystem。连接级 TCP 转发仍受 `AllowTcpForwarding` 和 `PermitOpen` 限制。客户端严格校验 SSH host key，转发后继续校验 TLS 信任根和 SAN。

## 生效配置证据

`sshd -t` 对副本基线和候选均返回 0。以 `getent passwd` 枚举的全部 **37 个 NSS 账户**为比较集合，覆盖盘点到的 3 个有交互 shell 的账户及其他账户。每个账户比对6类连接属性，目标端口均为 22。主机字段分别覆盖回环 localhost、远端数字地址和代表性 DNS 名。

| 连接类别 | 样例 | 对比结果 |
| --- | --- | --- |
| IPv4 / IPv6 回环 | `127.0.0.1` / `::1` | 74 组一致 |
| IPv4 远端，数字主机 / DNS 主机 | RFC 5737 文档地址 | 74 组一致 |
| IPv6 远端，数字主机 / DNS 主机 | RFC 3849 文档地址 | 74 组一致 |

**222/222** 组全量输出逐字节一致。另对设备身份在同一矩阵核对了 **18 个配置项 × 6 组**，包含设备公钥文件及全部限制项。代表性矩阵覆盖的是输入属性分类。实际源地址、目标监听地址及非枚举式目录身份需在外测预检中结合环境重新确认。

在私有副本挂载完成并准备好临时 host key 后，逐个账户和连接属性执行以下命令。任一差异或返回非零即停止。生效值及 diff 保存在私有目录。

```bash
/usr/sbin/sshd -t -f "$BASELINE"
/usr/sbin/sshd -t -f "$CANDIDATE"
context="user=$LOGIN,host=$CLIENT_HOST,addr=$CLIENT_IP,laddr=$LISTEN_IP,lport=22"
/usr/sbin/sshd -T -f "$BASELINE" -C "$context" > "$PRIVATE/baseline.effective"
/usr/sbin/sshd -T -f "$CANDIDATE" -C "$context" > "$PRIVATE/candidate.effective"
diff -u "$PRIVATE/baseline.effective" "$PRIVATE/candidate.effective"
```

## 隔离动态演练

| 检查 | 结果 |
| --- | --- |
| 设备认证及应用层 TLS | 固定目标通过严格 TLS 并返回 HTTP 200。替代地址、替代端口、exec 加 PTY/agent/X11 请求、反向转发、错误设备密钥、错误 SSH host key、错误 TLS CA、错误 TLS SAN 共 8 个负例被拒。PTY/agent/X11 与 tunnel 的独立禁用值已从 `sshd -T` 核对。 |
| 配置切换与管理连接 | `sshd -t` 后原子替换夹具主配置，向夹具监听 PID 发 HUP，等到新监听日志事件。切换后原有管理 SSH 传输仍能转发并返回 HTTP 200，新管理 SSH 会话也能执行命令。 |
| 手动恢复 | 用 `cmp` 确认恢复内容与基线逐字节一致。新设备认证失败。已有设备与管理传输都能继续访问 TLS 后端，说明恢复配置后还须处理已有设备连接。 |
| 精确吊销 | 移出专用公钥文件后，新设备认证立即失败，已有设备传输仍通。对两条已知设备连接用客户端 PID 关联 TCP 四元组，再确认服务端连接归属、监听父进程和设备身份进程名，仅向这两个连接的服务端子进程发 TERM。两个转发监听均释放，原有管理连接和新管理登录均通过。 |
| 定时恢复 | 预先启动 6 秒回滚计时。到期后自动校验并恢复备份、重读夹具配置、重新核对并终止登记的设备子进程。备份内容逐字节一致，设备转发释放，新设备认证失败，原有管理转发仍返回 HTTP 200。 |
| 清理 | 使用带硬时限的 `unshare --mount --net --pid --fork --mount-proc --kill-child --propagation private`。退出后移除私有临时目录，生产主配置及 Include 文件散列一致，现网 22、2222、443 的监听快照及所有者一致。 |

动态测试的关键命令如下。命令中的 PID、路径和端口均属于隔离夹具。

```bash
/usr/sbin/sshd -t -f "$SAVED"
/bin/cp -p "$SAVED" "$ACTIVE.next"
/bin/mv -f "$ACTIVE.next" "$ACTIVE"
kill -HUP "$FIXTURE_LISTENER_PID"
# 等待夹具日志出现新监听事件，再开新管理连接。
cmp "$SAVED" "$ACTIVE"

ss -Htnp state established "( sport = :22 and dport = :$DEVICE_SOURCE_PORT )"
ps -o pid,ppid,args -p "$DEVICE_CONNECTION_PID"
# 确认 TCP 四元组、设备身份和监听父进程唯一吻合后，在夹具内终止。
kill -TERM "$DEVICE_CONNECTION_PID"
```

## 外测前的放行条件

批准前继续使用当前 22 配置。独立复核需确认真实服务启动参数、Include 与当前磁盘快照一致，补齐实际管理来源的连接属性和现网 socket 激活下的恢复方法。用保留的管理会话和独立新登录检查恢复，预先武装自动回滚。若出现配置漂移、管理员生效值差异或归属不明确，停止试验。

本次精确终止依赖夹具已知客户端转发 PID。外部设备试验需要在服务器侧独立建立设备身份到全部活动连接的映射，处理并发新连接及 PID 重用，到期先拒绝新认证，再终止并复查全部活动设备连接。现网的连接定位与回滚联动在获准前单独确认。独立评审通过后，由协调方安排限时外部设备认证及严格 TLS/HTTP 正负例。
