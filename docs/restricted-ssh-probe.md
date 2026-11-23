# TITA-57 受限 SSH 转发验证

## 路线选择

建议继续优先验证独立 HTTPS/WSS 直连。现有公网 IP 的专用 443 若能从独立网络取得可信 IP SAN 证书和业务响应，Android 可沿用现有 TLS/WSS 栈和设备令牌，服务器也少维护一套密钥及连接生命周期。TITA-54 的 Mac 外测中，en0 的 443 TCP 超时，默认 utun6 的 443 TCP 握手后 TLS EOF。此前对 19453 也未取得公网 TLS 成功证据。项目 CA 可降低 ACME 接入依赖，公网端口可达仍须单独验证。当前没有已验证可投入使用的零采购直连入口。

在系统现有 22 上复用管理员 SSH 会使备用业务和运维共用入口及故障域。TITA-57 的授权边界内，现网 22 的已知连通性与独立 sshd 的应用层可达性是两项证据。本次夹具只监听 127.0.0.1，没有可用的独立外网入口。外部 SSH 握手、SSH 内严格 TLS 和 OPPO 独立链路均未验证。公网复核需要已有且明确授权的独立可达入口，或另行评审端口 22 的共存设计。

## 复核命令

基线为 main 的 `ce79deb94b5b63d774609726f2970981f317c052`。在已设共享构建锁的 Ubuntu systemd 授权测试机上，确保 runtime 空闲。夹具通过 `/run/lock/little-buddy/heavy.lock` 非阻塞持锁。依赖 OpenSSH、OpenSSL、curl、iproute2 和 sudo。

```bash
bash -n scripts/probe-restricted-ssh
sudo -n timeout --kill-after=5 100 bash scripts/probe-restricted-ssh
sudo ss -Hltp '( sport = :22 or sport = :22457 or sport = :24457 or sport = :25457 )'
systemctl list-units 'lb-ssh-probe-*' --all --no-legend
find /run -maxdepth 1 -name 'lb-ssh-probe.*'
getent passwd | awk -F: '$1 ~ /^lbssh/ {print $1}'
curl -q -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1/
```

实测环境为 OpenSSH 9.6p1、OpenSSL 3.0.13。正向传输通过临时 CA 和叶证书的 IP SAN 校验，访问合成 HTTPS 响应。最终运行 14 项通过。

| 组 | 数量 | 结果 |
| --- | ---: | --- |
| sshd 生效策略与会话/转发拒绝 | 6 | 精确策略、exec、PTY/agent/X11 会话、反向 TCP、网络 tunnel、同一后端的替代目标。PTY/agent/X11 共用一次会话打开测试，服务端在请求这三项能力前即拒绝会话，各自禁用项另由有效配置确认 |
| 两层身份校验与应用响应 | 4 | 错误 SSH host key 拒绝、正确 TLS 和 HTTP 200、未知 CA 拒绝、错误 TLS 身份拒绝 |
| 生命周期与吊销 | 4 | 客户端取消清理、服务端断连后的新传输和 TLS、移除设备公钥后新连接拒绝、重启专用单元后原连接断开且吊销继续生效 |

首次运行发现 PAM 启动的用户服务独立于专用 sshd cgroup。该临时用户服务已按其专用 UID 停止并删除用户。最终夹具禁用 PAM，并用不可用于密码认证的 `*` 密码字段及 nologin shell 建立临时身份，避免出现独立用户服务。

退出时按记录的客户端和后端进程及专用 systemd 单元回收，删除临时用户和 `/run` 夹具目录。专用 sshd 单元还有 120 秒运行时上限。最终复查临时端口、用户、目录和单元均已清理，现网 SSH 22 监听进程保持一致，Caddy 回环 HTTP 返回 200。若测试进程被强制终止，可先凭 `lb-ssh-probe-*` 单元名和对应 `/run/lb-ssh-probe.*` 核对归属，停该专用单元，按所列端口识别并停止夹具进程，再删除对应 `lbssh<随机后缀>` 用户和目录。

## Android 评审输入

以下为发布原始 JAR 的 HTTP Content-Length 和 POM 许可，实际 APK 增量取决于 R8、算法依赖和打包配置。项目最低 API 为 26，本轮未构建 APK。

| 候选 | 许可与原始 JAR | 接入和维护成本 |
| --- | --- | --- |
| mwiede JSch 2.28.8 | Revised BSD，含 JZlib 的 Revised BSD 和 jBCrypt 的 ISC。716,757 字节 | 先评估其通道或转发 API 与现有 OkHttp 集成。验证最低 API 的算法 provider 与 Android Keystore 签名适配，明确允许的算法并维护依赖更新。[POM 与 JAR](https://repo.maven.apache.org/maven2/com/github/mwiede/jsch/2.28.8/) |
| SSHJ 0.41.1 | Apache-2.0。599,970 字节 | POM 还有 SLF4J、asn-one 和 Bouncy Castle 运行时依赖，预计打包和 provider 兼容性验证成本更高。评估最低 API、R8、密钥签名和日志配置。[POM 与 JAR](https://repo.maven.apache.org/maven2/com/hierynomus/sshj/0.41.1/) |

若直连持续受阻且隔离外网入口通过复核，建议先用 JSch 做独立 Android 概念验证：设备密钥按安装实例配置，优先验证 Keystore 非导出私钥签名，固定 SSH host key 并设计受控轮换。转发只开放指定后端，并保留服务端 TLS 链和业务身份校验、可撤销设备令牌。若采用回环转发，连通地址与 TLS 业务身份分别配置。切换 Wi-Fi/蜂窝和用户取消时关闭旧 WSS 与 SSH 传输，再启动新业务会话。验证最低 API、签名发布包体积变化和 OPPO 独立网络后再决定是否纳入产品。

夹具用单设备专用单元重启来主动终止该设备的旧传输。若产品将多设备放入共享 SSH 实例，应设计按设备精确关闭已认证连接的机制，并验证其他设备会话和管理员 SSH 的连续性。
