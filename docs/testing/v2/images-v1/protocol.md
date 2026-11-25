## images_v1：默认图库与播放揭晓

显式依赖PR45 head be33588f905dd00ecacb0447d5bebab55e4eae17。不改host/parent/主Activity。客户端在bind可选features:["images_v1"]；不声明时不会收到新图片帧，保持旧语音兼容。

服务端真实读取assets/v2-default/manifest.json与60张PNG，校验PNG头、大小与SHA256。请求只接受工具枚举show_image/hide_image/generate_image和asset_id；没有URL/任意路径/远端正文。未知ID回退garden；文件损坏尝试garden，均不可读则无ready/reveal。generate_image目前没有动态Provider，source仍为default、fallback_reason=dynamic_unavailable，不能声称新图已生成。其他回退原因unknown_asset/asset_invalid。

所有帧沿用v=2、epoch、服务端seq。图片scope另含session/turn/revision/topic/token；token每次准备独立随机。topic是建议状态播放提交后的目标topic。

- image_ready：scope与asset_id/sha256/width=512/height=512/source=default/fallback_reason。只准预读和隐藏准备，不能显示。无需等图片IO就可开始播音。
- reveal：scope、effect="image:"+token、asset_id、sha256，以及player/stream/segment/end。只有该最后一句的最后PCM段完整ACK且图片真实准备完成后发送；两者可任意先后，未完成另一侧时等待，重复ACK不重复揭晓。
- hide：当前scope（无token）及reason=requested|input_changed。revoke同样取消旧图片。advance先暂停输出、取消旧准备并hide；换人/断开/输出撤销也使任务失效。迟到读取不得向新scope发布。

客户端唯一由b30实现：把已合图库打包到v2-default/png/<asset_id>.png，按本地清单验证ID/hash；ready不显示，reveal必须对应同一准备token、当前连接/epoch/revision/session/turn及已播segment/end。异步加载在每次实际显示前再次检查本地代际。hide/revoke/HOME/退出/新会话先撤销代际再隐藏；迟到回调不得重现。不得把服务端任意字符串变为路径。

普通对话及guess/story/adventure/association共用真实规划/审核/合成/ACK状态提交路径，工具最多一项。私事不准备图片。猜谜存在未公开秘密时，仅当秘密恰为answer、匹配默认素材名/ID，且最后一句逐字含“答案是<原答案>”或“谜底是<原答案>”才允许图准备；公开状态与answer.current事实仍等完整ACK。答案不匹配或其他秘密一律不揭图。

## 本地验证

python3 -m unittest tests.v2.test_images -v：9方法全部通过，普通8、负控1（移除播放门槛能被原安全断言检测）；子场景不增加分母。真实本地60 PNG逐一校验；语言/审核/语音明确为注入的合成夹具。编译及git diff --check通过。未重跑82/111/92集合、未调用云服务、未部署、无APK/设备/声学证明。原始日志tests.log。

边界：本PR交付后端准备/播放提交/取消路由与契约；客户端图片装配由独立组合PR验收。动态Provider、最终真实设备效果仍OPEN，不用默认素材冒充动态生成。
