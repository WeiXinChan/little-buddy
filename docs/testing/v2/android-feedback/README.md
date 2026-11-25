Android R15：私有反馈真实接线

基线从已审PR63固定79535e6起；只读确认root已把PR63、修正后的PR65和PR66合入main98762add2596194cff48213c873172fbd589bf6f后，本分支本地快进到该主线。未调用/重试GitHub合并或main ref更新。后端组合测试使用同一固定主线的独立干净检出，不用原40052候选。LLM由root切换deepseek-v4.1-flash-1017，客户端无模型回退、无模型调用，也未因模型另改协议。

实际调用链：家长验证→FeedbackPageFactory.configure(domain)→AndroidFeedbackRuntime创建FeedbackWireProvider并注入FeedbackCoreOwner/FeedbackEngine→已确认材料的submitAdmitted→独立/v2/feedback WSS。详情页显式refresh→FeedbackCore.refresh→provider.read→原始页面的replyIntent最终提交→父区TextView。后台只可重试已有原键删除，不读回复、不上传、不创建新父授权。无配置或不是已发行私有连接则available=false；有配置但服务离线，保持未确认状态，不自动重发。

每个网络操作先捕获原页面/取消代际，再准备不可变信封并完成TLS与feedback-v1 ready。最终ParentDomain.acceptProtected只执行READY→ADMITTED短内存决定；无网络、Keystore、JSON编码或文件IO持授权锁。实际Socket.send在决定后执行，HOME/取消/换页直接关闭原WSS/SSH及唤醒等待者。已经提交给socket队列的数据不能宣称物理撤回；超时单仍持久保留原id并可撤回。迟到reply不能借新页面epoch，材料等值到期或落盘stage后到期都拒绝新内容发布。Native页面在实际显示前独立重验同一材料时钟，排队UI过期不渲染；有材料时才启用到期清理回调，pause/close取消，离开或回到家长区不保留过期文字；到期只排本机sweep/列表，不远端读、不重传、不续Grant。

新提交key为[RFC9562 §5.7 UUIDv7](https://www.rfc-editor.org/rfc/rfc9562.html#section-5.7)：前48位保持Material.created毫秒，其余随机/version7/variant10；request仍UUIDv4。键先加密持久化，重启、读取、超时、撤回都不改时间或重铸key。不自动重发旧v4失败单。旧v4可读/撤回；无原设备凭据绑定的历史记录不能证明跨旧凭据全部副本删除，保守保持DELETING，不能借新token的未知键回执冒充完成。

本机材料schema1/2可读，写入schema3新增原凭据SHA256绑定与只缩短的服务端截止；不存第二份完整token。更换token时，旧记录删除拒绝借新设备身份，保留原键及失败状态。submitted/delete_by均用原始毫秒回执；刷新不改原提交时间、不延长截止。跨端时钟校验失败保持未确认，未建立全局可信时间。只有all_copies_deleted严格Boolean true且原绑定一致才可DELETED；false保持DELETING，网络/存储失败不假删除。仅本机清理与原源日志独立，不能冒充远端删除。

附日志默认关闭。实际V2 host只记录CONNECT/RECOGNIZE/PLAY/CANCEL等有限枚举、数字版本/计数；相邻重复stage合并；未采集的elapsed/usage为0，不作实际服务用量证明。不记录识别正文、聊天、音频、token。家长勾选时段后预览精确条数/范围/字节，再确认提交。日志copy在最终上传点再次核期限，过期不发送。回复只在已验证家长区显示，不触发儿童语音或通知。

私有传输：V2Ssh Target只有VOICE=/v2/voice与FEEDBACK=/v2/feedback；请求URL/TLS身份固定127.0.0.1:19483。每个实例JSCH本地绑定端口0取得独立随机端口，Socket仅把固定逻辑目标映射到本实例返回的loopback端口，远端仍固定127.0.0.1:19483。同CA/固定hostkey/StrictHostKeyChecking，禁代理、redirect和retry；无任意URL/端口入口。每操作独立池/socket/SSH，voice管理挂起保留连接也不占相同本地固定端口。Keystore私钥与已存token均无导出UI。

冷启动删除恢复只加载已有本地域/已有owner key，create=false，绝不为后台重建owner或父域。页面关闭不会撤销后续新页面Grant，但会取消其原网络操作。已排队的旧操作从ThreadLocal原scope与取消代际判拒，不能读取后来页面的新权限。

检查：scripts/v2-feedback-tests.py为受影响控制器/键/严格解析/最终admit/映射反例；scripts/test-feedback-client.py为真实认证TLS，对固定后端SQLite receiver仅使用合成材料，覆盖不附日志、选定日志、false副本回执、超时原键删除、握手撤销、迟到回复取消、凭据切换。测试ParentDomain真实逻辑、PIN/KDF与加密vault，系统owner签发使用明确fixture；Android JsonReader以缓存Gson的JVM端口执行。没有原生UI/Keystore/SSH或OPPO实测。

交付code18/2.0.0-rc4，独立包/原签名/原Parent记录保持，媒体PR63代码保留。voice契约不变，APK元数据另标feedback_protocol=feedback-v1。root仍负责启用私有接收库/实际副本清单与运营人、云审核/模型运行配置、最终真实SSH并存/设备验收。此PR不启服务、不部署、不派设备/云，不选外部平台或新账户，不发送真实材料。
