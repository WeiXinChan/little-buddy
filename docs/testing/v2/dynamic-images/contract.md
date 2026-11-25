R09 动态图片适配批次（生产默认关闭）

基线 main 4f165ee56008dd79c9c1f2b34102695fd2aafdda。新增具体 QwenImages HTTP 适配与 UnifiedProviders 注入端口；不修改 endpoint/voice/schema/Android。真实云请求 0；合成 HTTP 不证明账号权限、供应商审核有效性或生产可用性。

API 依据：[阿里云官方图像 API](https://help.aliyun.com/en/model-studio/qwen-image-generation-and-editing-api-reference)。显式北京 workspace、qwen-image-3.0 或 qwen-image-3.0-pro，POST workspace 的 compatible-mode/v1/images/generations，同步 n=1、b64_json、默认512x512；不跟随任何 URL/重定向，不自动推断 key 权限。官方资料不是本账号授权证明。

接入契约

```python
from backend.v2.dynamic_images import QwenImages, ImageConfig, ImageScope
images = QwenImages()  # disabled；不读环境、不借语音 key
# 审定资源后由独立组合层显式注入：
images = QwenImages(http, api_key=image_specific_key,
    config=ImageConfig(enabled=True, region='cn-beijing', workspace=workspace,
        model='qwen-image-3.0', resource_review_id=review_id,
        prompt_policy=prompt_policy_id, image_policy=image_policy_id),
    prompt_reviewer=review_minimal_safe_private_prompt,
    image_reviewer=review_exact_png)
providers = UnifiedProviders(speech, model, dynamic_images=images)
result = await providers.prepare_dynamic_visual(
    {'kind':'generate_image', 'asset_id':'cat'}, scope, is_current)
try:
    png = result.read_png()  # 再验 session/turn/epoch/revision/topic
    # 尚待实现的有界传输和客户端揭晓门禁；本批不发布到客户端。
finally:
    result.release()
# 撤销/换话题/退出：providers.cancel_generated_image(scope)
# 进程生命周期终止：await images.aclose()；借入的 HTTP client 由组合层关闭。
```

ImageScope 是本地上下文标识，不授予身份或权限。is_current(scope) 必须同步返回字面 True，读取现有会话/话题/媒体代际/到期/管理状态；撤销和取消应主动调用取消端口。每个 await 后重验，结果每次读取再验；不得把一次 True 当未来 IO 的许可。既有安全 TTL 不延长。旧 scope 的取消不能撤销新 scope。

现有 generate_image 工具没有自由描述字段：prepare_dynamic_visual 只接精确 kind/asset_id，按内置目录取名称，形成“儿童插画：猫”这类最小描述。更底层 prepare_generated_image(description,scope,is_current) 也必须先过同一审核，禁止传聊天、身份、原音频。生产 prompt reviewer 必须同时承担安全、隐私和最小化审核，不能只查字符串长度。

两个异步审核端口分别收 (description: str, nonce) 和 (canonical_png: bytes, nonce)，返回 ReviewDecision(True, sha256(精确UTF8/PNG字节), nonce, 已配置policy)。缺失、拒绝、错误摘要/nonce/policy、整数1均拒绝。回执仅是受信注入端口结果，不是账号权限或远端归属证明；测试用批准回执不得用于生产。图片去元数据后才审核，最终 hash 绑定同一字节。

约束与失败

每实例一个任务；总期限默认8秒、配置最大15秒，取消确认最多300ms。拒不确认则隔离实例，禁止自动重试/新任务。响应 JSON 原始体3MiB，PNG2MiB，严格 base64/重复字段/CRC/zlib/真实尺寸/行过滤校验；只收8位 RGB/RGBA 非交错 PNG，拒绝动画/尾随材料，剥离辅助元数据。尺寸配置512–2048，解压按尺寸有界。PNG 不兼容时明确拒绝，不把云格式兼容当已验证。

结果只持一个有界内存 buffer，默认15秒、最大30秒自动清除，取消/失效/释放清除自有 buffer 和 scope/hash/ID；新请求清掉旧结果。无磁盘写入、无材料日志、异常仅有限 reason 枚举。Python/HTTP 库的不可变副本不等于物理覆写保证；消费者必须释放自己的传输副本，不能持久化。外部 reviewer/HTTP 扩展须遵守取消和内存契约；隔离不是杀死不合作的外部服务。

下一必要接线（OPEN，不能称 R09 成品）

当前 VoicePeer 仍走已审 DefaultImage 静态回退，尚未调用动态端口。b30 唯一拥有 voice.py/companion.endpoint/schemas.ENDPOINT/Android。后续需独立审定：选路 generate_image→本端口；scope 精确同步既有撤销/TTL/管理/换人；保留已播 ACK、私事和未揭谜底门禁；定义有界 PNG 传输及客户端真实尺寸/hash解码、准备→已播揭晓→hide/取消/迟到丢弃与材料释放。不能把 GeneratedImage 冒充旧静态目录 DefaultImage 或直接接受远端 URL。本批不更改既有协议契约 ID，也不宣称旧客户端支持动态图。

唯一外部资源补齐表

| 项 | 现状/影响 | 最小解决条件 |
| --- | --- | --- |
| 生图账号资源 | 未提供已审 image-specific key、workspace/model/region 权限；默认 disabled | root 审定并通过独立 credential 注入，不读取/复用 V1 或语音 token；resource_review_id 仅记录审批引用 |
| 描述审核 | 只有强制端口及离线 fixture，无生产语义/隐私审核实现 | 指定已授权安全服务/策略及拒绝/超时契约，审核精确最小描述，不能测试回执放行 |
| 图片安全审核 | 强制精确 PNG hash/nonce/policy；缺真实图审 Provider | 提供已授权图审接口/策略和安全凭据入口，拒绝/不可用均不发布；同时核供应商保留、版权与儿童适用条件 |
| 传输/客户端发布 | 当前静态回退路径仍有效，动态结果仅内存端口 | root/b30 按上述最小跨线契约接入并审定，不在本树并改 |

不再次索取已由 root 询问的反馈平台选择，不新增部署、付费、设备或真实模型试验。
