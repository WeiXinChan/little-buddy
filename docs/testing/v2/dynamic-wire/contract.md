R09 images_v2 后端传输/展示契约（客户端待root接入）

协议 v2-voice2-safety1-images2-volume1-management1-end1。先收正常 scope.protocol_contract，再 bind.features=["images_v2"] 和 image_contract=精确协议值；不匹配拒绝。images_v1 只保留静态目录回退，绝不接动态图字节。

所有图帧使用JSON文本，image_v=2，精确scope=session/turn/epoch/revision/topic，并带token、asset_id、image_id、sha256、width/height、source。epoch仍是外层标准字段。token每次展示绑定更新，image_id标识同一短期材料。

动态图只在最终语音片段实际完整ACK后请求适配器：image_begin {bytes,chunks,chunk_bytes:8192,encoding:"base64",retain_ms} → image_chunk {index,offset,data} × N → image_ready → image_display {action:"display",duration_ms,retain_ms,segment,end,player,stream}。PNG≤2MiB、块≤8192原字节、N≤256、单JSON帧≤16000字节，传输总预算2秒，零URL。客户端按scope/token/image_id只收一条顺序流，校验连续index/offset、总大小、真实PNG尺寸、最终SHA256，准备成功仍不能擅自显示；仅匹配image_display及本地已播ACK后揭晓。任何不匹配/超时/新代际先清材料恢复眼睛，不接受跨scope拼接。JSON帧可与语音交错，不能依靠相邻帧归属。

image_display.action=display/extend/reshow/hide。揭晓/一般展示6秒、故事12秒，均在P06/P07范围。hide duration_ms=0，恢复眼睛；明确收起可在剩余保留期内再看。extend把当前展示截止向后增加同一展示时长；reshow重新有界展示，必要时重传同一内存PNG。每次duration_ms和retain_ms均从当前剩余期限向下取整，客户端不得晚于该保守期限；本地计时到期必须隐藏。retain_ms不授身份或新许可，不得因重复extend/reshow重置最终材料截止。

动态材料最终截止不晚于适配器结果剩余TTL，且≤15秒；静态短期材料描述也最多15秒。最终截止固定，hide/extend/reshow均不刷新；会话失效、换人、重连、管理暂停、私事/新谜底或实际话题变更会销毁缓存。仅普通收音revision/播放代际变化会隐藏旧图并取消未完成图任务，已经完整播出揭晓的公开缓存可在同一session/connection/topic的固定窗口内供明确图片控制请求重新绑定当前scope；这不是旧任务复活。

语义路由新增工具extend_image/reshow_image（无asset_id），hide_image沿用。仅continue且模式/规则/角色/秘密均与当前已播状态完全一致的图片控制允许借用公开短期缓存；控制确认语句完整ACK后绑定新topic/turn/epoch/revision并执行，不将新剧情伪装控制。普通内容的实际topic递增使旧缓存失效。模型只得到图片控制可用性，不得到图像字节或身份。修改设定走新的show_image/generate_image并清旧图。

每个await前后重验会话/turn/epoch/revision/topic/connection/output/player/stream、管理/私事/谜底和资源期限。发送已进入socket写入的旧帧不能物理撤回，客户端必须对scope及本地撤销代际再次拒绝；不持授权锁跨IO。服务端释放自有内存不证明Python不可变副本物理覆写。生产适配仍默认disabled，缺账户授权或任何审核资源不可发布动态图，无测试批准回执生产注入。无真实云调用/部署/设备验证。本批交后端可执行路径；Android传输解码/计时展示/恢复眼睛仍由root/b30接入验收。


R14音量契约：正常scope先建立预期session/turn/epoch/revision，再发送volume {v:2,type:"volume",epoch,session,turn,revision,control_v:1,direction:"up"|"down",token:32位随机hex}。没有识别正文、音量值或家长上限；不是Grant或长期设置。每个输入scope最多一次，重复seal不重发，即使写入失败也不自动加音量。当前完整端点判断volume_up/volume_down后直接发送，不先生成/播放回复、不唤醒暂停的播放器、不interrupt改变旧播放。客户端只接受当前WS/本地有效scope、精确control_v/direction和未见token，按家长上限限幅并去重；HOME/管理/换人/断线/过期先撤销该scope。迟到网络帧不可撤回，本地代际校验仍必需。结果回执本批不要求服务端调整任何权限/上限，不据回执重试。


实现/交付边界：正常未配置动态资源在完整ACK后发image_status {image_v:2,state:"unavailable",reason:"image_unavailable",session,turn,epoch,revision,topic,token}，无供应商正文，无重试；images_v1仍为明确静态dynamic_unavailable回退。静态images_v2不传PNG，ACK后image_ready(source:default)→image_display；客户端使用已打包目录并验hash。动态图源source:dynamic只能走上述字节流，不允许套用静态目录ID当动态载荷。隐藏先恢复眼睛，材料仅在固定短窗内保留；hide控制的确认ACK只迁移同一公开图片，不续期限。图像大小/传输边界及音量schema未改变read_request/helper或budget的实现。

OPEN只剩本批外边界：root/b30的Android新协议拼块/解码/计时/恢复眼睛、语音音量轨道限幅与去重回执；生产生图专属账号授权及描述/图片审核资源仍缺且默认关闭；真实云、真机、声学和长稳未测。新协议须匹配APK及release-manifest再发布，旧images1契约APK不可冒称匹配本批。没有重新打包或部署旧发行制品。测试供应商/图审均为明确隔离fixture。
