# Code33 failure 的有限服务端观测

基于 main `a7d12b7cea6d5afbf2418f8b4369ba5c5e9753a7`，保留152/153/155；不修改冻结155/156、Android、V1或部署。现场 code33 第二个请求的供应商/PLAN/FACTS/review/TTS 根因仍 UNKNOWN。

## 已有证据与缺口

第一请求的 lastspeech→实际 HEAD 为3947ms，firstaudio→HEAD42ms，不支持“手机缓冲几秒”的判断；一个样本不能认证 P12 median/P95。第二请求已 endpoint/seal/open/bound，随后 `failure code=voice`，没有 audio/head。BOUND 只证明客户端绑定，不证明 PLAN/FACTS/审核/TTS 已成功。

源码审查：`VoicePeer._respond` 的 `last_failure` 仅是易失 peer 属性。生产 live/server 没有持久化或查询接口；既有 task-local Trace 默认关闭，只有隔离诊断工具主动保存。没有可据此取回该次异常的既存安全持久记录。本轮未读原 journal、进程内存、异常正文或音频，也未重复实际请求。

## 最小观测

`backend.v2.live --observe-failures` 显式启用；默认不创建观测窗口、不附加 peer observer、不产生观测记录或日志。原易失 `last_failure` 仍存在，kind 也改为严格类映射，不使用任意 `type(...).__name__`。

窗口从创建时起固定900秒，最多准入4个已鉴权 peer，每 peer 最多4条、总16条，任何一项耗尽即不再采集。新连接不续期/重置总额度，同 peer 不重复取得额度；无自动重启或重试。只在异常收尾路径记录一次，不轮询、不开新任务、不改变 Trace 128上限。observer 抛错/返回异步对象后停用，不能影响原 failure wire、播放、释放或业务结果。

输出是固定 `service=little-buddy-v2,event=bounded_failure` 的单行 JSON：stage/kind/contract/detail、相对窗口 elapsed_ms、临时 peer/record序号及数值 turn/epoch/revision。无用户/会话UUID、私域正文、转写、PCM、候选、exception message、URL、凭据、供应商body。未知值为 `unknown`，不是任意字符串。白名单来自固定源码及既有合同枚举。记录前检查 Session对象/connection、原 operation 的 turn/epoch/revision/output/private 和取消状态；响应 operation 无 revision 时另核捕获的 response_revision。读身份不调用 `_live`/`valid`、不续租。只持 weakref，不保留完成 peer/异常/任务历史。

保留现有阶段含义：`safety` 是 whole审核阶段，`synthesis` 同时包含逐段审核与TTS路径，不凭该标签宣称一定是TTS供应商。仅覆盖原 `_respond` 合法当前 operation 的异常收尾，不冒充 ASR/endpoint、monitor timeout、协议解析或已失效操作的全量事件审计；没有记录也不能反推“没有失败”。

root审后如决定部署，可在原V2启动参数中追加此开关；必须继续使用既有 `LogNamespace=little-buddy-v2` / `SyslogIdentifier=little-buddy-v2` / stderr journal，不改默认journal、转发、V1或保留策略。现有独立namespace六天内部目标及七天要求边界继续适用；历史共享副本问题仍OPEN。本PR不自动改unit/安装/重启/启用。后续读取仅筛选上述固定event的白名单JSON，不读取原异常日志。也可在隔离入口注入同步私有sink，不创建公开接口。

`release.selected` 自动包含新增 `backend/v2/failure_observer.py`，对应测试已验证。

## 受控复现与验证

复用生产认证 loopback TLS、VoicePeer.run、Session、真实schema校验、端点/PLAN/FACTS/whole/segment门禁与wire ACK，只有供应商是固定合成实现：solo完整ACK后，普通介绍第一轮完整ACK；第二轮同一文本进行快照续说/advance，取消旧端点，再完整seal/stop/open/bind。无注入时可继续完整ACK；分别注入 PLAN锚点类型、FACTS来源、whole安全审核与TTS异常时，记录准确阶段/类/合同，保持原 failure wire、0新增audio/0候选state提交和清理确认。这个复现不证明手机具体是哪一种注入。

另验证默认关闭、900秒/4peer/16条/每peer4条、跨连接不续期、stale/private/管理/过期租约拒记、observer异常/异步返回隔离、未知类/恶意元数据脱敏和包选择。所有真实供应商调用0，无手机/部署/重启。

最终112项相关离线回归 PASS（含上轮unknown/取消/时限、安全质量分离、格式repair、runtime配置与TLS认证）。最初测试客户端忘记消费 decision→stop/open/bind，5个等待failure子例超时；修正的是客户端驱动，不是产品放宽。sparse checkout缺少仓库内图片/Android帮助源码的两次阻断也原样保留，补齐文件后运行，不添加skip。

```sh
scripts/with-build-lock python3 -m unittest -q tests.v2.test_failure_observer tests.v2.test_post_solo_probe tests.v2.test_stage_timing tests.v2.test_facts_diagnostics tests.v2.test_plan_diagnostics tests.v2.test_plan_format_repair tests.v2.test_facts_safety_help tests.v2.test_review_separation tests.v2.test_image_runtime tests.v2.test_flash_text_config tests.v2.test_m04_transport
```

不改变审核、deadline、0.5秒退出、共享repair名额、模型或调用预算。本轮只交新诊断能力供root独立审，不以随机重跑、切模型或降低质量来解决未知fault；下一次真实二case观测由root另外安排。
