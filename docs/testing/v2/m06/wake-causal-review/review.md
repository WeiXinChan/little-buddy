本轮仅本地冻结，供 root 决定后续发布/构建。未 push、未触发 CI、未构建 Android。基线本地 b3a392a1518eefab9b17595e28a97dc25725a196（tree cdcb7ca0d78ff4a94547e96a4310d2c563ee3c62），远端 PR36 基线 12bb29eb1e178d7a56dfefe56ebb5f920a854df8。PR36 HOLD，M06/A01/A27/F01 OPEN。

## 因果屏障

`BuddyActivityTest.nativeWakeFlowsThroughProductAudioAndTlsAsr` 两次正控均等待：本次 OPEN_SOCKET 计数、本次 ASR_UPLOAD_END 在该连接之后、当前连接的 PCM_BUFFERED 在该 END 之后，且停止按钮可用，再 Stop。不再把“结束录音”按钮可用/END 本地入队当服务端完成；回复时录音按钮可能关闭，因此不保留这个不适用的等待条件。

源码依据：wake 初始许可 segments=0；private_fixture.Fixture.finish 只有收到完整 END 后才校验既有原始 PCM exact，失败抛错；之后才产生答复。AnimalActivity 在 segment.end 校验/封口完成后经 dispatch(current socket) 发 PCM_BUFFERED，旧 socket 不会满足本次屏障。没有新增生产事件、没有更改生产 stop/cancel 或发送路径。脚本原 exact2/sealed2 及两个 turn 的 exact=1 断言原样保留。

新增真实 loopback TLS 负控分别覆盖两个原始 fixture/连接：服务端第一批 write 被 Event 暂停，客户端实际发送全部 PCM+END 后，exact/seal/reply 不能提前完成；放行 write 后，原 exact 校验完成仍暂停 finish 返回，reply 仍未完成；放行响应后验证真实 binary PCM、segment.end 和对应 key 的 ACK/commit，再关闭连接。全程无新增 sleep，Event 等待/任务回收有界，失败 finally 释放屏障并取消/join 客户端任务。这证明发送 END≠服务端消费≠回复/ACK，不冒充 Android 调度回归。

## 正常 V2 workflow 待审方案

移除固定 b2 artifact 下载、精确 b2 fetch/reuse、JVM NOT_RUN/伪 0；以当前 checkout 串行执行 testV2DebugUnitTest，记录真实退出码，再 assembleV2Debug/assembleV2DebugAndroidTest，保 --no-daemon --max-workers=1 与 v2Test/v2Emulator/v2SyntheticProbe。unit 失败仍可采集独立设备证据，但最终门失败；assemble 失败不安装/不回退旧包。根 Gradle/verification/wrapper 输入变化也触发 workflow。

撤除已结束 HDA 对照的强制 feature 和 preboot guard，显式 M06_REQUIRE_HDA=0；不更改运行时 HDA 安全实现/负控。PA-only 私有隔离、原生产 Capture/source7、完整 mic 矩阵、九组门、native 只读取证、原采样授权和 SDK false 清理均保留。此恢复不会解决现有弱 PCM，也不将 mic/确认未证项变绿。根审定后才决定新匹配构建/一次必要 CI；本轮没有新的 HDA 实验。

Android test 已变，b2 的测试 APK 不再匹配拟交付树，不能纳入 host-only 复用 guard。已有 a2be/2266 只作历史证据，当前树 APK/JVM/设备/新 global wake2exact 全部 NOT_RUN。本轮不改任何 app/src/main、backend 运行时代码、格式/阈值/TTL/SDK。

## 验证与历史

- 后端 test_animal_cloud 全模块 13 PASS，含新增双连接因果屏障及既有 wake exact/seal 门；backend-tls.txt。
- host suite 91 PASS（CI 关键环境，RequireHDA=0）；host-tests.txt。首跑 90 PASS/1 FAIL 为已撤 HDA 实验的 workflow 静态期望，原日志另存，未删除失败历史；仅同步此正常 workflow 静态期望，运行时安全负控不改。
- YAML parse、每个 run block bash -n、git diff --check PASS；没有执行 workflow/模拟器/录音/云调用。
- global90 API36 job138889361730：设备36/36、SSH/JVM TLS PASS，但独立 wake-flow sealed1/exact1（要求2/2）整体 FAIL，保留；API26 job138889361437 SUCCESS。不能推断原失败缺哪个 turn 或取消/日志晚到的实际原因，本次修正正控的因果假设。
- CI31 root 验收为 FRONTEND_FORCE_OFF 成立、guest 正 HDA card/driver 缺证 STOP，fixture NOT_RUN、九门16 PASS，review6050913754。后续镜像研究由 TITA100 接续，无新 HDA CI。

建议 root 先核本冻结 diff，特别是 current socket 回复段屏障及正常 workflow 去除实验覆盖的边界，再授权匹配 Android 构建与常规 CI。后续必须仍看到两个服务端 exact/seal 才可认正控通过，不能以本地 TLS 通过替代。
