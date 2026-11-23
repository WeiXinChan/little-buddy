# TITA-62 现网 SSH 22 设备 Match 离线复核

**结论。** 本机配置副本的生效参数比对通过。在 TITA-63 复核后，以服务端成功认证记录核实实际管理连接。同一隔离夹具结合双栈继承 socket、发起会话退出后的 systemd 自动回滚，以及按现网认证宽限期执行的设备排空。当前仅交独立复核，限时外测由协调方另行放行。

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

**222/222** 组全量输出逐字节一致。另对设备身份在同一矩阵核对了 **18 个配置项 × 6 组**，包含设备公钥文件及全部限制项。代表性矩阵覆盖的是输入属性分类。下面另列现场快照和启动参数。

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

## TITA-63 复核补测

### 实际管理连接与启动参数

从服务器侧 `ss` 获取 TCP 22 已建立连接，在 `/proc` 中将 socket 归属关联到现网监听进程的直接子进程，再与本次开机的 `ssh.service` 日志关联。只有 `Accepted` 记录的 PID、账号、远端 IP 和端口全部吻合，日志单调时间晚于进程启动且进程身份复查一致时，才计为已认证。`[priv]` 标题可以在认证完成前出现。快照确认两条已认证管理连接，同属管理身份 M1，均使用同一实际 IPv4 来源 S1 和同一本机目标地址 L1。M1、S1 和 L1 均为脱敏代号，同一代号表示同一值。用原值运行矩阵，只保留计数及结果。

| 身份覆盖 | 来源 → 目标 | 启动条件 | 全量生效配置结果 |
| --- | --- | --- | --- |
| 全部 37 个可枚举 NSS 账户，包含 M1 | 6 类代表性连接属性 | 实际启动选项 `-D` | 222/222 一致 |
| 同一批 37 个身份 | S1 → L1:22，IPv4，`host=S1` | 实际启动选项 `-D` | 37/37 一致 |

只读核对 `ssh.service` 的 ExecStart、运行中监听进程标题和该进程是否有非空 `SSHD_OPTS`。实际启动为 `/usr/sbin/sshd -D`，无额外启动覆盖。`ssh.socket` 的 `Accept=no`，systemd 和 sshd 共享 IPv4 与 IPv6 两个通配监听。实际管理连接的本端 L1 来自已接收 socket 的本端地址。`UseDNS no` 在各比较配置中均已确认，因此实际连接的 `host` 使用数字源地址。设备身份在每组连接属性上均通过 **18 项限制**检查。补测仍用原 Include 路径和排序，`sshd -t` 对两份配置均通过。

网段、地址、身份及进程号只在验证期间本地使用。现场快照只覆盖当时已建立的两条连接。外测预检应以当天观察值重跑，并核对计划使用但快照中未出现的管理来源。

```bash
systemctl show ssh.service -p ExecStart -p MainPID
systemctl show ssh.socket -p Accept -p Listen
ss -Htnp state established 'sport = :22'
journalctl -b -u ssh.service --grep='^Accepted ' -o json --no-pager
/usr/sbin/sshd -T -D -f "$BASELINE" -C "$context"
/usr/sbin/sshd -T -D -f "$CANDIDATE" -C "$context"
```

### 发起会话退出后的自动恢复与认证竞态

夹具在独立 mount、network 和 PID namespace 内运行，使用权限均为 `0600` 的合成 passwd、group 和 shadow 文件。未读取或复制现网认证数据库、授权密钥或 host 私钥。夹具监督进程持有 IPv4/IPv6 两个监听 FD，按 `Accept=no` 的交接方式通过 `LISTEN_PID` 和 `LISTEN_FDS` 传给隔离 sshd。启用候选后及回滚后均核对两个 inode 同时由监督进程和 sshd 持有，并分别读取两种地址族的 SSH banner。定时单元由真实 systemd 运行，监听 FD 由夹具监督进程交接。

1. 两条设备传输经固定回环目标 `127.0.0.1:24457` 使用严格 TLS 并各返回 HTTP 200。第三条在服务器接受公钥探测后暂停签名，服务端成功认证计数仍为 2。另建立一条尚未声明身份的 SSH 连接。
2. 用 `setsid --wait` 启动独立发起会话，由该会话执行 `systemd-run --on-active=2s` 创建专用 timer 和 service，随后退出。服务确认发起 SID 无剩余成员，原 PID 和启动时间已消失。它核对夹具进程启动时间和三个隔离 namespace 后，通过 `nsenter` 进入夹具。
3. 服务先移出设备公钥文件并实测新设备认证被拒，随后语法检查、原子恢复备份并重读夹具 sshd。恢复配置与备份逐字节一致，双栈监听 inode 保持一致。
4. 服务通过 established socket 归属、监听父进程和 sshd 进程身份识别设备连接。发信号前打开 pidfd，复查进程启动时间、父进程、身份和 socket 归属后定向终止。尚未声明身份的连接留给 sshd 认证宽限期处理。扫描同时检查尚未进入 socket 视图的监听子进程。连续四轮无设备或未分类子进程才报告排空成功。

候选、备份和现网矩阵均采用 `LoginGraceTime=120s`。排空上限 **135 秒**，给认证宽限期留 15 秒余量。回滚单元 `RuntimeMaxSec=155s`，给撤钥验证、恢复和重读留 20 秒余量。外层复跑硬时限 180 秒。两条路径按顺序执行，各使用独立夹具。

| 路径 | 注入条件 | 收口检查 |
| --- | --- | --- |
| 正常 | 一条未声明身份的连接在定时器武装前进入夹具 | sshd 按 120 秒宽限期自然关闭连接。终止两条已认证和一条待签名设备连接，排空耗时 117.8 秒，回滚单元 `Result=success`、`ExecMainStatus=0`。 |
| 超时 | 排空开始 25 秒后另建一条未声明身份的连接，其 120 秒宽限期晚于 135 秒排空截止 | 截止时该连接仍开着，未被定向或批量终止。回滚单元 `Result=exit-code`、`ExecMainStatus=42`。基线已恢复且设备公钥持续撤下，两条已认证和一条待签名设备连接已终止。该窗口按失败处置。 |

TITA-63 复跑附件放在同一工作目录后，顺序执行：

```bash
sudo -n timeout --kill-after=4s 180s bash tita62-followup.sh normal
sudo -n timeout --kill-after=4s 180s bash tita62-followup.sh timeout
```

超时演练的外层脚本仅在确认回滚单元按预期返回 42 且各项隔离断言通过后返回 0。

两条路径均确认双栈继承监听、既有管理会话收发以及新管理登录可用，并再次确认新设备认证被拒。夹具退出后回收专用单元和临时文件，现网配置散列及 22、2222、443 的监听归属一致。

外测仍待 TITA-63 独立复核及协调方放行。最终开窗前按实际计划使用的管理来源和目标地址复跑矩阵。Mac banner 仅证明对应路径到达现网 22，外部设备认证、应用层 TLS/HTTP 和 OPPO 路径尚未实测。
