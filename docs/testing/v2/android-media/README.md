Android真实媒体路径：R14 / R09

依赖：已合PR61 main1bc25be832cfd590ef799aef3e7b288922c7696d，包含root补齐volume_up/down端点提示词。精确协议 `v2-voice2-safety1-images2-volume1-management1-end1`；先正常scope握手，再images_v2/image_contract精确协商。本PR不改后端源码或systemd发行配置。

语音音量事件：VoiceClient核当前socket/local lifecycle、session/turn/epoch/revision、control_v/direction/一次性token及当前响应期限；ChildVolume固定10百分点夹在0..家长上限。Playback.setVolume真实调用AndroidTrack.setVolume，更新当前AudioTrack；新AndroidTrack以当前临时值初始化。暂停不play/resume，mute标记保持0音量，失败已消费控制且不重试。不写ParentDomain长期设置；HOME/管理/换人/旧scope清授权，重连为新的临时会话。

动态图：单JSON≤16000 UTF8字节；image_begin最多2MiB、8192块、256块，2秒总预算。按完整scope/topic/token/image_id/asset_id/hash/尺寸/source逐帧匹配连续index/offset。image_ready完成顺序接收后交串行worker：验证SHA256、canonical PNG CRC/IHDR/IDAT/IEND、512..2048实际尺寸、完整有界inflate，再BitmapFactory bounds和真实解码。单decoded slot，无URL/文件落盘；静态目录始终校验已打包60图manifest/hash，不将动态图当目录ID。

完整本地已播player/stream/segment/end ACK与当前image_display匹配后才揭晓；ready或异步decode完成均不授权显示。视图直接ImageView.setImageBitmap，隐藏View.GONE露出真实眼睛。初次一般6s/故事12s由服务端毫秒字段向下取整，客户端计时隐藏；extend字段是服务端已经计算好的剩余展示时间，不重复相加。材料最早deadline从首次本地retain_ms固定，后续只能缩短，最长15s；hide/reshow/extend/重传均不续期。

普通输入隐藏公开缓存、取消未完成组装；generic revoke销毁像素/未完成任务，只保留同连接session的非授权image_id→最早截止墓碑（最多256个）。这允许已合服务端在明确控制确认ACK后重新绑定/重传，又不能无限刷新本地TTL。旧图不能仅凭墓碑显示。管理/HOME/断线/换人硬清所有状态。已排队解码任务取消或到期会清原始bytes；正在执行的原生解码不能保证物理中断，结果在落地重验后丢弃并回收，绝不发布。Bitmap回收排在UI移除旧引用之后。

过期image_display hide(reason=expired/eyes=true)无ACK坐标，只能匹配当前材料做隐藏/释放，不可能显示或续期；正常display/extend/reshow/hide仍需新完整ACK。image_status unavailable恢复眼睛，不把缺动态图Provider当普通语音故障。生产缺动态资源仍依后端failclosed，无测试图审回执注入。

定向验证入口：scripts/v2-media-tests.py（原ImageGate受影响集合+新增scope/限幅/组装/期限/晚到释放）；scripts/test-media-client.py（真实认证TLS→生产VoiceClient→Playback→AndroidTrack与AndroidImageRoute）。后者服务端为恶意/正常协议fixture，Android native对象为明确JVM端口；真实PNG签名/CRC/尺寸/inflate校验执行，原生BitmapFactory/AudioTrack实测留最终设备，不冒称已听到或见到真实设备效果。--negative只删除AndroidTrack mute保护，保留原断言，必须真实失败。

候选code17 / 2.0.0-rc3，独立包com.littlebuddy.sim.v2，API26+/arm64-v8a，内部Debug签名；同签名向上升级保留本地记录，换签/卸载/降级无保留保证。旧code16包保持原hash。root负责后端release/systemd新契约与真实账户/审核资源/设备最终集中验收；本PR不部署、不派设备、不跑云/旧全集/旧CI。
