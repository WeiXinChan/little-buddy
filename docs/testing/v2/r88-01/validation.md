# R88-01 首批针对性验证

base `379045c50f0ea234f19401ba2b8c82fda75f0528`；独立树`v2-functions` / `agent/tita-87-functions`，不包含b30未合客户端/host代码。

原M10报告/证据经认证CLI读取。`original/test_m10.py`逐字节匹配指定PR44 `e0d543f13bf55889454c01765cf3d4cac8f83c24`，未改assert/oracle、未标skip/expectedFailure。QA原失败日志另存qa-original-failure.log；本轮把每个旧backend Python文件从固定git提交导出到隔离cwd/PYTHONPATH后运行原断言，**8执行、7通过、1失败、0跳过，exit1**，见old-help.log/json。

最终最小检查：

| 检查 | 实际结果 | 分母说明 |
|---|---|---|
| `M10_REQUIRE_HELP=1`原QA方法 | 8/8通过，0失败/跳过，exit0 | 含原失败变通过，及原QA的两项负控方法 |
| 新增R88/配置针对性方法 | 15/15通过，0失败/跳过，exit0 | 含1项新负控方法、1项认证loopback真实TLS WebSocket |
| 合计方法 | 23执行，23通过，0失败/跳过 | 正常方法20＋负控方法3；子场景不膨胀分母 |
| Python编译 | py_compile成功 | 5个生产模块及测试，不是Android/APK构建 |
| 静态图库检查 | 已合60张PNG哈希一致 | 仅资源可用性，不重新宣称视觉质量/显示已验收 |

三项负控方法：原QA移除字面护栏、绕过语义审核，确实观察到禁止文本进入合成；新增把安全failure code回退为voice，原R88接受断言实际抛AssertionError并被负控捕获。它们是有明确期望的负控，不把子断言失败计入普通安全场景通过，也不是16个Kotlin突变的重跑。最终源SHA-256和分母见verification.json，原始stdout/stderr见new-help.log/targeted.log。

新增方法覆盖503/超时/非法审核/false分类、后句失效不合成、单一固定ID与已建立scope、明确求助在模型故障时零模型调用、普通虚构/角色求助不误触发本地前缀保护、聊天与四玩法已播状态、advance/换人/取消/过期及transport yield拒绝旧帮助、解除失败response budget但不延长idle TTL、literal配置解析/禁止shell替换/缺凭据拒绝。loopback测试调用实际runtime配置构造→DashScopeModel→UnifiedProviders→voice_server/VoicePeer，经真实认证WSS发送控制帧并收到固定帮助payload；供应商HTTP被明确Mock、合成器是合成输入，无设备/真实ASR/TTS或云模型采样。

复现：

```sh
M10_REQUIRE_HELP=1 python3 -m unittest discover -s docs/testing/v2/r88-01/original -p test_m10.py -v
python3 -m unittest discover -s tests/v2 -p test_safety_help.py -v
python3 -m py_compile backend/v2/{voice,companion,safety,runtime,live}.py
```

按用户功能优先要求未重跑82/111/92全套、Android/声学/设备/长稳/旧CI；无新增重构建，不占heavy.lock，Linux仅轻量编译/针对性软件回归。未部署、更改V1、修改阈值/TTL、生成真实凭据或发新云采样。

本批服务端R88与现有模型配置接线可独立审合；b30的本地可见帮助/合法离线voice须组合，当前不冒称客户端已可见/可听。动态图库路由、工具/游戏集成补全、A12来源压缩与M12成本版本仍是后续功能批次，集中资源缺口见resources.md。完整V2、实际语义模型效果、跨功能/设备/长稳/声学最终验收继续OPEN。
