## 管理暂停/取消退出：management_v1冻结协议

依赖PR49 6ecb1afe5abcbc5fb866ff576e2d35ca5655bb80。依据docs/v2-requirements.md R14：验证/管理页暂停儿童收音、播报和迟到输出；管理音频不进儿童上下文，原会话仍按原期限保留；取消/退出无需PIN，回待唤醒，不续播。R07/R13过期、断线、重启不承诺恢复；R16明确单独换人清空。

仅在现有认证WebSocket内使用，不是跨连接恢复端点，不是家长Grant/PIN授权，不可修改受保护设置。host必须在UI入管理前先本地停收/停播/隐藏图，再发pause；只开本地专用取消/退出检测，管理PCM绝不上传。HOME/失焦/退出应用按既有生命周期政策清Grant并关闭/结束连接，不得拿该receipt复活旧页。正常取消/退出也清本地Grant，但可由当前页面退出操作消费当前receipt回待唤醒；这不恢复任何管理权限。旧页面/已撤回操作不得调用恢复，host重验当前页面操作代际，后端只验证连接/会话/暂停scope，不假称能验证未上传的本地Grant。

1. 如尚未从正常open/bound获得scope，发`{v:2,type:"scope",epoch:E,seq:S}`。服务端返回`scope`，含epoch/session/turn/revision与management_v=1、state=active|paused|waiting_wake|expired。不发送上下文、不触发ASR/模型、不延长期限。
2. `management_pause`：`{v:2,type:"management_pause",epoch:E+1,seq:0,session:SID,turn:T,revision:R+1}`。SID/T必须来自本连接可信scope；R是当前版本。原子更新epoch/revision、置管理暂停，撤销所有旧媒体身份和图片准备，清capture/analysis/queued decision、取消ASR/生成任务，再回`management_state`：state=paused、session/turn/revision、epoch、management_v=1、pause=<32位随机hex receipt>。暂停确认前客户端仍必须本地隔离。重复入子页不重发pause；普通seq保持既有严格单调。
3. 管理中只接受heartbeat/scope/end和合法management_resume；input/probe/seal/wake/advance/ACK/stop/resume_noise等儿童媒体事件直接丢弃，不解析或保留其PCM，不调供应商、不延长idle TTL。同epoch丢弃帧仍按既有严格seq消费；丢弃帧不能推进epoch。heartbeat只保原有传输lease，不延长会话idle TTL。
4. `management_resume`：`{v:2,type:"management_resume",epoch:E+1,seq:0,session:SID,turn:T,revision:R+1,pause:<原receipt>}`；这里E/R是paused确认值。只当前连接/当前暂停receipt且未过期可用，先消费receipt，再重置epoch/revision/媒体代际，回management_state state=waiting_wake，pause=null。保留已播事实、游戏、未揭谜底及本次私事分区，保持原expires；不发open、不建player、不重播、不复用旧录音。后续真实wake/wake_solo才离开待唤醒并遵循已有新请求/stop/open/bind流程。未唤醒前其他媒体输入丢弃。
5. 同连接结束/到期回state=expired，不可恢复；关闭连接需重新认证并用新Session，绝不承诺重连恢复。错误scope/revision/receipt不能移动epoch或刷新期限。相同receipt不可二次使用；旧操作即使迟到也不能跨新页/新会话生效。provider取消/资源释放无法确认时沿既有quarantined关闭，不能声称可恢复。

pause receipt只防控制串台，不是身份/配置授权。PIN错误、取消、管理闲置锁定等本地流程不需要后端识别管理口令；后端不会看到管理话语。b30唯一实现host/parent/VoiceClient生命周期与本地检测，本批只改backend与针对性测试。

## 同批路由补接：正常结束

核路由发现R07/R16明确告别/全体结束没有规划action，只有客户端end能清会话。新增plan action=end：简短告别经审核及最后完整ACK后clear全部会话材料、revoke，再发session_end，字段v/epoch/session/turn/revision/reason=conversation_ended；同连接run随后退出，不复活。未完整ACK、管理抢占或取消不得提早结束；管理退出本身不使用end，而使用management_resume→waiting_wake。“不玩这个了”仍leave，“我先退出，你们继续”仍共同会话continue，含糊退出只确认。host消费session_end回待唤醒，下次唤醒创建新认证连接/新Session，不能复用旧scope。无远端正文或管理口令识别。
