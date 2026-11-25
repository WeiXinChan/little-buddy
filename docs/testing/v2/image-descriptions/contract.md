R09 去身份化最小描述与有界生图尝试

基线main c1461044fcf11a2d88544b68bd7ad714831dcf74，包含PR59/60/61/62和root的volume枚举修复。协议仍为v2-voice2-safety1-images2-volume1-management1-end1，不变更Android wire、图片分块或音量字段。

真实调用路径

```json
{"kind":"generate_image","asset_id":"cat","description":{"subject":"cat","color":"blue","outfit":"spacesuit"}}
```

PLAN语义模型从孩子本轮明确图像请求提取受限字段；本地校验后转为内存MinimalDescription。UnifiedProviders.prepare_dynamic_visual将其渲染成“儿童插画：蓝色的猫，穿着宇航服”，沿已有QwenImages→ModelImageReview.prompt→同步生图→ModelImageReview.image→PNG传输执行。合成检查实际运行上述具体生产类和VoicePeer，不是未调用端口；全部HTTP为MockTransport，真实推理0。

subject必须匹配asset_id及已审60图库目录。其余可选color/outfit/setting/action/prop，枚举定义在image_descriptions.py并进入schemas.PLAN，组合支持蓝色小猫穿宇航服、修改为红色小猫穿雨衣等。没有自由文本、身份字段、任意URL或从上下文拼接整段描述的入口。每一视觉特征必须同时出现于本轮请求/已播公开heard之一，以及最后一句待审核的公开描述；现有语音安全审核通过并完整已播ACK后才真正请求图片。私事/不相关/未说出的特征、注入、未知枚举、目录主体不匹配拒绝工具，保留正常对话。当前明确颜色/服装改口优先于旧公开设定，显式否定不得借旧heard覆盖。

仅本轮有明确画/看/修改意图标记才允许自动规划generate_image；普通对话不每轮生图。此意图门是主模型语义规划外的保守本地约束，不声称覆盖所有自然语言。无description且本轮没有自定义视觉特征时兼容原目录名称生成；若孩子明确给了颜色/服装等而PLAN遗漏描述，拒绝工具，不退成普通主体；显式取消/不要生图也拒绝。有自定义字段但无法满足、审核拒绝或旧images_v1客户端，不用普通默认图冒充自定义成功。受限词汇以外的任意新主体、精细属性和所有措辞未覆盖，不能称无限制图像描述或整个R09成品。

材料生命周期

MinimalDescription只持规范化插画短语的有界bytearray（≤160字符/480 UTF8字节），不保留原话/身份/完整caption/source上下文；未发送提案15秒自动失效，timer弱引用不持活取消任务。提案销毁、派发成功/失败/取消均清空自有材料；已释放描述不能重复调用或悄悄退回目录描述。上游既有会话/turn/epoch/revision/topic/输出/私事/谜底门禁和所有图像审核继续有效。Python不可变副本物理覆写不在证明范围。

预算与实际成本边界

当前live/server复用同一UnifiedProviders，实例内ImageAllowance跨会话/重连共享：最多4次/滚动3600秒、间隔至少15秒，在任何图片审核/生成之前同步消费；失败、取消、拒绝不退款。仅保存最多4个monotonic时间，不保存会话、身份或描述。限额/冷却拒绝发生在审核网络前，语音对话继续；不是家长预算页面或整个服务硬截止。重启/多进程会各有账本，不替代root已配置供应商预算。

root提供2026-11-25北京公开价卡（附件rate-card-reference.json，非账单；不假设免费/优惠）：qwen-image-3.0输出0.18元/张，4次限制只给成功图片参考量0.72元，绝不等于所有语音/模型/审核成本≤3元。fun-asr-realtime为0.00033元/每次输入秒，重复probe上传重复计入；CosyVoice-v3-flash 1元/万计费字符、汉字权重2；qwen3.8-flash输入0.8/输出2.7元每百万token，须计端点/规划/事实/安全/压缩及两道图审。失败/取消计费、固定失败交代TTS以及实际用量仍须最终真实计量，当前无新增计费功能或云调用。[官方模型计价](https://help.aliyun.com/zh/model-studio/model-pricing)、[官方Qwen Image 3.0说明](https://help.aliyun.com/zh/model-studio/qwen-image-3-0)。

明确请求失败的实际语音路径

本地PLAN把明确请求工具标成ExplicitImageRequest（非wire字段、非权限证明）。VoicePeer.prepare_visual异常分支先释放未发布图材料、发既有image_status，再调用image_failure_speech。固定已审句：“这张图暂时没生成好，我们先接着聊。”只在原session/turn/epoch/revision/topic/connection/output/player/stream仍有效、原输入预算尚有余量且未暂停/等待唤醒时，通过原synthesize/audio/ACK路径最多尝试一次；不新建Session、预算、身份或模型上下文，不先恢复暂停播放器，不重试生成或TTS。

交代的public文本只附在最终音频片段，完整ACK前不算已听；部分ACK、取消或超出原预算时撤销仍属于该原播放的未完成材料，迟到ACK不能提交。后来的合法新turn/output/player不被旧finally撤销。完整ACK后复用reply_end回到监听。子输入/管理/HOME/过期直接丢弃旧交代；装饰性/非明确请求无声音副作用。Voice改动仅该异常分支及新帮助函数，read_request/audio/预算实现和root端点提示词均保持。

root最小配置差异：无。现有image.json/专用credential用途及ModelImageReview实现已由root配置/核实，本批不读取凭据、不重复索取资源；configured_not_cloud_verified仍不等于账号生图授权成功。生产真实合成/供应商审核效果、匹配APK实际显示与最终声学/长稳仍未测，root统一验收。本批不重跑已合PR61全集、不部署、不派设备。
