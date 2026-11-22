# Mac 一键 OPPO 离线回归

使用 Mac 普通终端的 Python 3.9+、OpenSSH 和已有 Android Platform Tools。手机需已启用 USB 调试，信任现有私有 TLS 开发 CA。首次手机授权和 SSH 提示由操作者确认。远端需要既有 systemd、免交互的维护 sudo、Python 夹具依赖及原证书文件。本工具使用独立的 9444 回环隧道和离线合成音频。

使用 TITA-20 中已交付的 0.1.12 原始双 APK。两份放在同一个目录。审核记录见 TITA-24，哈希、签名证书指纹和夹具提交固定在 `manifest.json`。工具核验本地和已装双包的字节，原附件哈希绑定审核过的签名、版本和 runner。安装仍由 Android 执行签名及版本兼容性检查。

解压工具并进入工具目录。将下面的远端路径替换为原来执行 `scripts/with-private-animal fixture` 的服务器 Git 检出，将双 APK 放到当前目录，然后在普通终端运行一条命令。

```bash
python3 run.py --checkout '/远端/原检出路径/little-buddy' --apk-dir . --install --scenarios release,late,blackhole,disconnect
```

- 已安装审定双包时可省略 `--apk-dir . --install`。只传 `--apk-dir` 时附加校验下载文件。覆盖安装时应用包授予调试所需运行时权限，测试包原位覆盖。
- 缺省执行八个场景，固定按 asr、first-pcm、between、playing、release、late、blackhole、disconnect 顺序。有多个设备时带 `--serial`。默认 SSH 目标为 `ubuntu@43.139.76.15`，可用 `--ssh-target` 覆盖。使用系统 OpenSSH 默认身份和用户 known_hosts。首次出现主机密钥提示时应核对指纹。
- 默认遇 FAIL 或 SKIP 停止。可用 `--continue-on-failure` 继续已安全清理的场景。若提示已有 9444 转发、夹具或 reverse，请先结束自己上一次的会话。若手机在测试中断开，报告会指出未能确认的清理。
- 每次运行生成私有目录 `little-buddy-oppo-*`。把其中的 `oppo-report.zip` 发回工单即可。包内有中文摘要、JSON、JUnit XML 以及失败时可取得的 `AnimalTiming` 数值记录。报告省略序列号及地址。工具只生成本地报告。

远端从固定 Git 对象读取夹具，不需要切换检出分支。每个夹具由一个 SSH 通道持有，正常停止或通道关闭后回收。进程运行上限 180 秒。测试使用已存在的私有游戏 instrumentation，测试会启动调试 APK 并设置离线回环入口。报告只计这次选择的场景，历史 0.1.11 的四项 OPPO 通过记录保留在 TITA-20。

替身测试命令为 `python3 -m unittest discover -s scripts/oppo-regression -p 'test_*.py'`，从仓库根目录执行。Mac、OPPO 和首次交互式密码流程仍需实际环境确认。
