# Concrete image review ports

`ModelImageReview` implements the prompt and PNG review ports required by `QwenImages` using an explicitly configured Beijing `deepseek-v4.1-flash-1017` chat-completions client. Construct it with reviewed workspace/key/policy IDs and inject `prompt_reviewer=review.prompt, image_reviewer=review.image`. It has no ambient credential defaults. `live.py` explicitly composes these reviewers with the generator only when protected image configuration is supplied. Omitting configuration leaves generation disabled.

The prompt request contains only the bounded minimal description. The image request contains only a canonical, bounded generated PNG as a data URI and a fixed review instruction. Neither carries conversation, audio, scope, nonce, identity, cookies or client default query fields. Responses must contain one finished assistant JSON decision with exactly one literal boolean `allow`. Denial, ambiguity, truncation, duplicate fields, malformed input, HTTP errors, redirects, cancellation or timeout do not approve an image. Receipts bind the exact reviewed bytes, caller nonce and policy ID; the generator still rechecks scope and its original overall deadline. The model policy is a content safety signal, not a guarantee of suitability.

References: [official DeepSeek model and visual-input support](https://help.aliyun.com/en/model-studio/deepseek-api), [official visual input format](https://help.aliyun.com/zh/model-studio/vision), [official image API](https://help.aliyun.com/en/model-studio/qwen-image-generation-and-editing-api-reference).

Validation: `python3 -B -m unittest discover -s tests/v2 -p test_image_review.py -v`. Seven targeted methods cover request minimization, PNG digest binding, actual generator→prompt reviewer→image reviewer rejection, malformed/truncated decisions, bounded HTTP failures and cancellation. All requests use synthetic HTTP transports; supplier inference requests zero. Reviewed runtime configuration, account permissions and actual model safety/effectiveness remain pending. A successful read-only permissions query with no matching authorized records is not proof of inference permission or its denial.


## Actual startup configuration

`backend.v2.live --image-config /protected/image.json` is supported for both `--check` and actual serving, in addition to the existing TLS/device/service flags. Preflight reads protected regular files using the existing stable-descriptor credential checks. The image workspace must equal the speech service workspace. Only the fixed reviewed policy identifiers below are accepted, not arbitrary allow-all policy names. The optional configuration does not change V1 or write any server state.

```json
{"enabled":true,"region":"cn-beijing","workspace":"REVIEWED_WORKSPACE","model":"qwen-image-3.0","review_model":"deepseek-v4.1-flash-1017","resource_review_id":"OPERATOR_REVIEW_REFERENCE","prompt_policy":"wali-image-prompt-v1","image_policy":"wali-image-png-v1","width":512,"height":512,"timeout":8,"result_ttl":15}
```

Credential directory additionally needs `dashscope-image-key` and `dashscope-review-key`, each operator-owned mode 0600. These are explicit purpose-bound inputs: an operator may provision an existing authorized provider credential for these purposes; the application never silently borrows the speech key. `resource_review_id` records the operator decision; it is not remote permission proof. An image config containing exactly `{"enabled":false}` needs no image credentials.

For systemd, supply these files through separate `LoadCredential=` entries and add `--image-config %d/v2-image-config` to both live preflight and serving commands. Do not enable such a drop-in until resource authorization/configuration is reviewed. The existing shipped default unit remains images-disabled. No actual service/drop-in/credential changes were made in this batch.

Four additional targeted runtime checks pass: omitted/disabled config without credential reads, strict workspace/model/policy and credential permissions, exception teardown, and actual `serve_checked` provider assembly (listener/suppliers replaced with non-network fixtures). Ten affected release/preflight/real-loopback TLS lifecycle checks also pass. Thus 21 targeted checks pass in total; this is not a full regression or real cloud acceptance. Production configuration/account permission and actual model safety/effectiveness remain pending.
