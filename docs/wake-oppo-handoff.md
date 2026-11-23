# OPPO 唤醒工程复验

协调方按单 runtime 派发。工件目录中的 `BUILD-INFO.txt`、`SHA256SUMS` 和 `bundle.sha256` 固定本次源码 SHA、APK 文件哈希、应用 ID、版本、签名证书和 TLS CA。使用已授权的 Ubuntu SSH 别名接入现有服务器。本次工程包使用独立 ID `com.littlebuddy.sim.wakeprobe` 与 `com.littlebuddy.sim.wakeprobe.test`。旧产品包和数据留在设备上。

## 获取、执行与回传

以下命令从空的 Mac 私有目录执行。将 `SHA` 设为工单提供的 40 位提交，`OPPO_SSH` 设为现有服务器 SSH 别名，`OPPO_SERIAL` 设为已授权设备序列号。Mac 需安装 Android Platform Tools、Build Tools 35.0.0、系统 Perl，OPPO 当前为用户 0 且已解锁。保持原设备锁屏设置。若安全锁屏要求凭证，记录门控通过与否以及无法继续的用例，并回传已有结果。

```bash
umask 077
remote="/home/ubuntu/tech/tita42/$SHA"
scp "$OPPO_SSH:$remote/wake-handoff.tar.gz" "$OPPO_SSH:$remote/bundle.sha256" .
shasum -a 256 -c bundle.sha256
tar -xzf wake-handoff.tar.gz
test "$(cat SOURCE-SHA)" = "$SHA"
cat BUILD-INFO.txt
shasum -a 256 -c SHA256SUMS
scripts/check-wake-fixtures wake-probe-test.apk
adb devices -l
result="wake-results-$(date -u +%Y%m%dT%H%M%SZ)"
if scripts/wake-oppo-probe "$OPPO_SERIAL" "$OPPO_SSH" "$remote" "$result"; then
    echo "回归通过"
else
    echo "回归未通过，保留已有证据"
fi
test -f "$result/exit-status.txt"
scp -r "$result" "$OPPO_SSH:$remote/results/"
```

执行器先验证工件和样本，然后拒绝已存在的隔离探针包或调试端口。安装命令为 `adb -s SERIAL install -g wake-probe.apk` 与 `adb -s SERIAL install -t wake-probe-test.apk`。每次仅清理本轮安装的隔离包，避免沿用其服务配置。结束时只移除本轮创建的两个包和 ADB reverse。若执行器异常终止，先核对本轮安装的包和映射，再清理这些资源。保留手机既有 CA、产品包及 8443、8444、9444 通道。

服务端通过 SSH 管理的临时非 root fixture 使用部署已有的回环服务器证书，从服务器现有 Python 环境启动，20 分钟上限。APK 内只固定该回环测试 CA。SSH 将 Mac 的 19446／19447 转发到服务器同端口，ADB reverse 将 OPPO 同端口接到 Mac。假 ASR 与 TTS 均在回环夹具运行，真实麦克风读回值在进入 KWS／处理链前被固定合成 PCM 替换。

## 结果判定

- `flow.instrumentation.txt` 一项通过。贯通使用真实 Sherpa JNI 和正式 Activity。待机零连接，紧接「玩猜动物」和单独回应后的「玩猜动物」均完整保留首字样本。回环日志恰有两次连接、两次首 PCM、两条 `exact=1`。本地回应前麦克风已释放，播放释放后才进入续听。
- 九个撤销用例分别在停止、退后台、设备睡眠三个窗口释放迟到的真实 KWS 后续指令回调、已接收的 `turn.ready` 或完整云端音频段。每项只执行一条 instrumentation 测试。旧代不得新建连接、发送结束或启动播放。聚合回环日志恰有六次连接、三次首 PCM 和三条 `exact=1`，音频段场景在撤销前完成三次假 ASR。锁屏结果以日志中 `keyguard_locked` 另记，屏灭而未进入系统锁屏时仅计屏灭撤销。
- 夹具来源、生成步骤与样本哈希由 [前台唤醒验证](foreground-wake-validation.md) 和 `scripts/wake-fixtures.sha256` 固定。APK 安装前同源与 APK 内 PCM 要逐个匹配。只回传用例计数、版本、音频操作状态及测试结果。OPPO 工程测量无法替代家庭暖声、童声和长期误报验收。
