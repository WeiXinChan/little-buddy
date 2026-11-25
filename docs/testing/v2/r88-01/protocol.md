# R88-01 首批：独立本地帮助与真实服务配置入口

固定已合main `379045c50f0ea234f19401ba2b8c82fda75f0528`。本批只改backend/v2与针对性测试/协议，不改host/parent/VoiceClient/主Activity/feedback后台。b30已接受以下单事件契约并负责客户端实现；其PR42依赖及后续Android修改不混入本树。这里不是全功能完成声明，图库/工具路由、A12压缩及M12后续批次仍须接续。

## 故障协议

正常认证后的`open`与`bound`顶层都有`session`、`turn`、`revision`（bound原identity不变）。后端响应始终等待播放器正常bind后才可能发安全故障，客户端不得从故障本身首次学习scope。

安全失败顺序：先原`revoke`清旧播放/图，再单个failure：

```json
{"v":2,"type":"failure","epoch":0,"code":"safety","session":"已由正常控制帧建立的ID","turn":1,"revision":0,"local_help":{"v":1,"prompt_id":"safety_support_v1","reason":"review_unavailable"}}
```

`reason`只有`review_unavailable`、`content_blocked`；不带输入、未审模型候选、私事、上游错误或远端文案。503、审核超时、非法JSON/布尔/重复字段均不可放行合成，并走前一原因；明确拒绝和既有字面护栏走后一原因。直接明确以“救救我/有人打我/有人伤害我/我想伤害自己/我不想活了”开头的求助也可不调模型进入本地帮助；这是有限字面支持策略，不声称完整语义检测。正常猫船长虚构、句中角色求助不会被该本地前缀策略一概拒绝，仍需正常语义审核。

帮助来自固定ID，本后端不再调用故障审核/LLM/TTS链路凑提示。响应自己的revision被捕获；advance/换人/取消/关闭/过期/transport yield后不借新scope发帮助。安全故障解除旧response deadline与输入准备状态，保留原idle TTL；不会在本地帮助中继续触发同一失败云响应超时或自动重试。

## 客户端归属与行为（b30已接受）

先核当前WebSocket对象、epoch/revision以及正常帧建立的session/turn；记录有限枚举，interrupt停止旧录放与图片，然后绑定自己的新本地生命周期代际。不能只空status；显示固定本地文字，并仅在已有合法离线中文voice可用时用系统TTS，不触发下载或网络语音。无离线voice时仍须显示，听觉能力缺口明示。HOME/退出/新会话/管理入口取消旧提示，提示期间不运行儿童收音上传。未知version/prompt/reason拒绝。

固定文案v1：“我们先停一下。我现在不能安全地继续这个回答。你可以找信任、愿意帮助你的成年人；如果你正感到害怕或可能受伤，先到安全的地方。”不固定要求找父母，不假称已通知他人。客户端实际呈现、离线voice及设备结果由b30批次/最终集中验收补证，本PR不冒称已完成。

## 配置入口

backend.v2.runtime实际构造现有DashScope、DashScopeModel、UnifiedProviders，供live主入口使用。新增`--service-env`只读取6个已审核模型/区域/workspace字段，按literal解析，不shell-source，不修改环境或V1文件；`--credential-directory`读取现有dashscope-api-key，不复制或生成密钥。默认仍兼容systemd注入的模型环境和CREDENTIALS_DIRECTORY。

`live --cert --key --token-file`仍独立必需，voice_server继续要求TLS/随机设备凭据；模型API key和V1 device token均不能当作V2归属证明。`python -m backend.v2.runtime --service-env <既有配置>`仅打印去workspace/凭据的模型清单，无推理请求。具体资源与缺口见resources.md，CLI参数见live-help.txt。
