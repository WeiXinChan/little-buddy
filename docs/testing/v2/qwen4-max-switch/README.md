# V2 Qwen4-Max switch

The owner selected `qwen4-max` on 2026-11-26, replacing DeepSeek for V2 text and image review through `backend.v2.models.TEXT_MODEL`. The Beijing endpoint and existing credentials are reused. The generator remains `qwen-image-3.0`; speech models and V1 remain unchanged. There is no fallback. Explicit `enable_thinking=false`, strict JSON schemas, request limits and safety checks remain in effect.

Official capability and price reference: https://help.aliyun.com/zh/model-studio/qwen4-max (checked 2026-11-26): Beijing text/image input and JSON Schema supported; uncached input CNY 10 / million tokens, output CNY 30 / million tokens. This is a rate reference, not a measured session bill or proof of account quota.

Existing DeepSeek probe evidence is historical and retained. A new release must pair the model selection in code with protected service and image-review configuration. Do not relabel the deployed rc6 bundle or its inventory as Qwen4-Max.

Validation: all 271 Python V2 tests passed. Two synthetic requests using the existing Beijing text credential returned HTTP 200: strict text schema in 1281 ms (90 input / 6 output tokens), and public illustration image understanding in 2127 ms (296 input / 6 output tokens). This proves that credential can access both modalities for these requests; the separately configured review credential still needs validation through the concrete reviewer. No child data or device audio was sent.
