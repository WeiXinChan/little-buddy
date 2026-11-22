# 猜动物模拟 APK 验收

本包基于 TITA-18 / PR #9 的 `56d7ac8`。猜测、提示、静默、三题计数、换题、揭晓与再玩都由同一个 Python `Session` 判定。Android 使用真实 AudioRecord 和 AudioTrack。假转写通过文本和按钮注入，音频只留在手机内存，回复使用字幕与 24 kHz 提示音。六张应用内矢量示意图为本次原创开发资产，随调试 APK 分发，待用户检查辨识度。

## Mac 安装与假服务

在固定实现提交的仓库目录运行。假服务只监听 Mac 回环地址 8765，USB 反向转发到手机的同一端口。原单轮服务和配置继续沿用。

```sh
shasum -a 256 -c SHA256SUMS
adb devices
adb install -r -g app-debug.apk
adb install -r app-debug-androidTest.apk
python3 -m venv .venv-animal
.venv-animal/bin/python -m pip install -r backend/requirements.txt
adb reverse tcp:8765 tcp:8765
PYTHONPATH=backend .venv-animal/bin/python -m animal.fake_server
```

首次准备依赖需要联网。之后一次启动用最后两行。结束时在服务终端按 Ctrl-C，再执行 `adb reverse --remove tcp:8765`。关闭模拟游戏入口可使用排除游戏代码的 release 构建，或继续从本包首页进入原模拟和私有语音单轮。若需完全回到 0.1.8，低版本覆盖可能被 Android 拒绝，卸载前先确认本地数据影响。

## OPPO 验收

保持 OPPO 解锁且应用在前台。在另一终端运行以下自动测试。

```sh
adb shell am instrument -w -e class com.littlebuddy.AnimalActivityTest com.littlebuddy.sim.test/com.littlebuddy.SimUiRunner
```

1. 首页点一次「玩猜动物」。首次启动按系统提示授权麦克风。每次等到「正在听」，填「告诉我答案」并点「结束录音并提交模拟回答」。连做三题，检查图在揭晓提示音播完后才出现，完成数在庆祝整轮播完后才加一。摸头应立即变表情，声音与继续流程保持。第三题后填「再玩」并检查新局归零。
2. 每次在收音、等待或播报按「停止」，另跑一次锁屏再解锁。应清图、回待机、无自动开麦。重开时先等旧音频释放。分别切换「末 ACK 先到并重复回执」和「延迟播放释放通知」，交叉四种配置重复。勾选「扣留揭晓段确认」再开一局，揭晓后应无图且不计数，最终超时清局。
3. 两次猜错触发揭晓征询，填「不要」，再试「提示」、错答和单独「是」，检查仍留在原题。另开一局揭晓两题后连续「换一个」直至六卡耗尽，检查没有再玩征询。
4. 注入静默后填「是」，确认重播原题并重新等到「正在听」。连续注入两次静默检查清局。填写「我想聊天」检查提示后回待机。注入断线后应可从空局重开。

设备记录请附机型、ColorOS 版本、成功次数及可见失败现象。成人或模拟结果仅支持工程验收，童声识别及真人合成语音效果留待后续阶段。
