## M12现有运行参数、延迟与成本边界

依赖PR48固定head ffe9dae3035b6ea017c2cf00f194b3d3531b84ee。本批不启动listener/部署/云请求，模型配置沿PR45只读确认的现有项目配置。snapshot.json归档本机实际Python/httpx/websockets版本、配置模型别名、部署参数以及旧日志的SHA256和原结果。模型别名不是供应商不可变revision，不把requirements pin当已安装版本。

既有服务：Beijing，Fun-ASR实时、qwen3.8-flash、CosyVoice-v3-flash/longanyang；配置存在不证明V2已获配额或V1 token可当V2授权。V2监听显式127.0.0.1:19483、TLS≥1.2，必须另给cert/key/token-file；service-env仅六字段字面量白名单，credential-directory只读既有key，不复制/生成/改V1。max_tokens=1400、thinking=false、24kHz、会话原65,536字节预算均未改。默认图已能真实回退；动态图片/真实反馈删除/配对归属恢复缺口继续集中在PR45 resources.md，不虚构成功。

DashScopeModel在真实HTTP调用路径新增有界累计延迟直方图（6桶，无逐请求正文/ID）、失败/取消分开计数。合法usage=0与缺失/畸形usage明确区分，token总数仅累加实际报告值。metrics()返回脱离内部容器的快照；不记录输入/输出、header、workspace、key或原异常。覆盖范围只是LLM客户端HTTP，非ASR/TTS/设备/E2E。缺价格和账单时monetary/currency=null，不能把未计量写成0元。金额与ASR/TTS费用仍OPEN；不新增云采样或收费。

历史docs/testing/v2/m05/live-model-final.jsonl原结果13项10通过3失败，27请求、prompt12608/completion1367。原报告median771ms/max12154ms包含历史混合测试，不代表当前新head或声学通过；失败原件和哈希保留，不改写成13PASS。该历史无金额账单/ASR-TTS成本/不可变模型revision，snapshot明确缺失。

新增最小4方法通过（正常3、未知金额误写0负控1）；真实HTTP adapter接MockTransport，校验known/zero/missing/非法usage、503/取消与有限桶、manifest不带密钥。编译/diff通过，原始tests.log。不重跑全套82/111/92，也无APK/设备/长稳结论。最终模型体验/耗时与真实账单、声学集中验收；不擅自开通付费或做新采样。
