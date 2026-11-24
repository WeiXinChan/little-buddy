CI25 必要 host-only schema 修复，PR36仍HOLD。

CI24 attempt1：模型创建9152ms超过8秒permit，READ前SOURCE_START_REVOKED；未注入。attempt2：本次nonce/source7/session89 READ及gates通过，但modules JSON被错误要求index，KeyError发生于observer启动/注入前，0包、无RPC、setTrue0；清理SDK false/observerStopped。二者不记为弱PCM或SDK校准失败，校准NOT_RUN。原件14976381004及14975754285（后者SHA457d4bca8041bfceb69b308c9ca6f6984797262dbf7259297c06e95fd7cfcc96）保留。

已在Ubuntu24.04隔离提取1:16.1+dfsg1-2ubuntu10.1的真实Pulse/pactl包运行私有-n服务器，只加载native-unix及两个null sink，没有播放或采样。真实pactl16.1完整modules JSON只有name/argument/usage_counter/properties，无index；list short modules文本提供ID。官方v16.1源码亦一致：https://github.com/pulseaudio/pulseaudio/blob/v16.1/src/utils/pactl.c （get_module_info_callback）。本地启动及查询后已终止/等待owned子进程，无系统安装。

修复：同私有server有界查询short modules，严格UTF-8解码；只解析数字ID/白名单name，不保留参数；ID唯一且数量/名字多重集与JSON一致，随后原拓扑校验sink owner_module、两个null monitor、QEMU归属。JSON固定白名单字段仅记录类型/数量，无参数/属性值。模块缺失/重复ID/未知模块/错误owner/坏UTF8均拒绝。失败记录阶段、异常类与项目文件行号，不保留任意异常消息。回归覆盖bounded bytes→module_summary完整路径，不能只手工str直接调用解析器。

工作流精确fetch b2，解决新增提交超过fetch-depth2时的来源解析。仍复用b2原APK、JVM NOT_RUN、不构建Android、不跑source6、不改TTL/音量/阈值/原mic及九设备断言。CI25仍需取得真实SDK校准/波形/live/新鲜度结果，host测试不能替代。
