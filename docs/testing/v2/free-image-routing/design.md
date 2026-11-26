免费优先生图：实现前安全核查与冻结设计

基线cf187d4d35490726e3ce996c6cbe3df678a65a67；不动root/v2-rc8、APK或真实配置/凭据。qwen4-max文本及审核保持。

官方依据：[Qwen图像API](https://help.aliyun.com/zh/model-studio/qwen-image-generation-and-editing-api-reference)列出2.1 Turbo/Pro的同步URL返回，并示例精确host dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com；本批只信该host，不扩大为OSS通配符。[免费额度规则](https://help.aliyun.com/zh/model-studio/new-free-quota)说明403/AllocationQuota.FreeTierOnly；控制台余额与开关才是账户事实，本地次数不是账户额度。

冻结路由：显式image配置model=Turbo、fallback_model=Pro、free_tier_only=true（管理员审定两者用完即停）；可配置单独Pro作管理员切换。默认未配置/disabled仍拒绝。仅403、严格有界JSON中的精确code、无产图数据时切Pro一次。未知403、超时、余额问题、已产图后下载/图审失败均不切模型。两者明确耗尽后实例停止新图片请求，保持既有可解释失败交代；不猜剩余10张，不自动回3.0。原3.0仅保留显式旧配置兼容，绝不在免费路由中。

安全取回：单独httpcore pool（已有锁定依赖），不借供应商httpx客户端，不携Bearer/default headers/cookies/proxy。HTTPS固定host/443、无用户信息/重定向/片段，严格PNG路径和URL长度；DNS所有地址须公网，核验后把实际连接固定到字面IP，TLS SNI/证书仍核原host，防二次解析换址。禁止私网、本地、混合DNS及过渡地址。读写/TLS/DNS边界复核同一lease。一个GET、流式原始PNG≤2MiB、无解压响应、MIME/length检查；返回原checked_png做真实512/CRC/zlib检查、去元数据、nonce/hash绑定图审后才可发布。客户端不见供应商URL。

整个Turbo/Pro尝试共享原deadline、单任务/取消隔离、n=1、512、短期材料清理及既有逻辑尝试预算；prompt审核一次，最终PNG审核一次。无无限重试；已成功出图再失败也不得额外生成。仅URL/原始缓冲存在本次协程内存，不写盘/日志；Python不可变副本物理覆写不作保证。

验证先用合成API、合成DNS/连接及真实PNG，不碰真实云。原图片适配/运行时/审核/描述/传输套件运行；另验证严格quota路由、URL/SSRF/header隔离、DNS固定和时限/取消。root审查后只作有限真实单图及配置切换；实际返回host若不在上述官方可定位信任范围，拒绝并由root审定，不临时扩白名单。
