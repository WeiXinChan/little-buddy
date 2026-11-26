## 精确 a717 下载适配

基线 e3ce683fd44b2083fe8e51f34726083fc4b85a23。生产代码仅 image_download.py。
仅允许原 dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com 与新增 dashscope-a717.oss-accelerate.aliyuncs.com；无 OSS 通配符。
依据：root 两次受控失败诊断及明确授权；官方 FAQ https://help.aliyun.com/en/model-studio/qwen-image-api （How do I get the domain name whitelist for image storage）列出 a717 示例，但说明 bucket 可变。本改动不据此自动信任其他 bucket。

validated_url 精确检查 authority；每次下载从合法 URL 选定 host，绑定 PublicOutputBackend 和 GuardedStream。DNS 只解析选定 host；检查所有记录后以公网 literal IP 单次连接；httpcore/h11 从同一 URL 产生 Host；TLS 必须使用该选定 host，且保持 CERT_REQUIRED/check_hostname。即使另一个 host 也在许可表，跨 host SNI/连接仍拒绝。下载池无共享客户端、代理、Bearer、cookies、重定向或重试。

## 验证

命令见 tests.log：原 103 方法 + 新 7 方法，共 110 执行 / 110 PASS / 0 FAIL / 0 SKIP。其中沿用 4 个显式负控检测方法，不当作额外真实云证明。新 7 方法含两个 host 的真实 httpcore/h11 请求编码、合成 networkstream/TLS 边界检查，以及跨 host SNI/连接、跳转、后缀/用户信息、混合私网/site-local DNS、TLS 验证关闭等反例。所有 DNS、TCP、TLS 流均受控替身，未建立真实供应商连接；不是实际证书链验证证明。

public_addresses/FREE01、dynamic_images 免费路由/总 deadline/lease/取消/字节/MIME/PNG512/双审核、模型和 Android 均未修改。未读取 secret 或生产配置；0 云调用、0 实际 DNS、未部署/合并。保留两份 root live FAIL 原件；此前审核/生成 HTTP200 不代表端到端通过、免费余量或账单结论。独立 QA 后由 root 决定第三次有限真实单图验证和配置切换。本地不保证全账号额度。
