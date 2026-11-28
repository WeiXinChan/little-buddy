# V2 首次表达流式 ASR：默认关闭候选

基线 `9046eee10c14bb4f1fbc09dc8ccead40b43dfbe6`；仅 Backend V2。PR160测量工具保持冻结，不改client34、wire、V1、模型配置、部署或审核并行逻辑。本轮不启用、不发云请求、不做手机动作。

## 已有证据与收益限度

root已独立执行唯一old/new ASR-only固定合成配对：49413 samples、同PCM SHA、相同完整转写、normalized参考相同；ASR2/text0/TTS0/image0、各1start/1finish、资源退出确认、reader pending0、无强杀。old/new说完→final 941.725/456.765ms，released 1093.649/609.620ms。按所给数值相减：final差484.960ms、released差484.029ms，两个边界分开，均非本PR再次测量。usage原值duration3各一次，单位/价格/额度/账单未知。这是单对Linux合成结果，不是phone/P12、p95或童声证据。code33第二SERVERVOICE根因及局部提示phone未覆盖仍OPEN，不能用流式性能优化关闭它。

## 实现与所有权

只有服务端显式开启 `stream_asr=True` 才具备能力；正式CLI为 `python3 -m backend.v2.live ... --stream-asr`，省略即关闭。没有环境变量隐式启用，也不宣告新wire字段。现有服务定义没有增加此flag。

`VoicePeer`记录真实wake的session/connection许可；首个已校验的speech PCM才为本表达预开一个raw lease。wake/barewake/advance/非speech PCM均不单独创建。wake之前保留过capture时，该表达不允许提前上传，避免预上传pre-wake字节；正常legacy probe不因这项优化而改变。每次清空capture建立新expression token，lease绑定session对象/ID、connection、turn、epoch、private mode、capture对象/token和原input budget对象。raw lease不是Operation，不获得发布或context权限，也不构造revision=None的Operation。

单写任务独占offset；available仅由已收到并校验后的capture长度推进，chunk最多6400字节，await前后核归属/原budget，handle(input)不等待网络write。capture仍限640000字节，除了每块不可变副本，不为raw lease另复制整段。多个speech/quiet revision保留同一原始资源；只有真实当前probe捕获精确Operation和冻结长度N。writer flush到N才finish一次，不发送越N字节，最终文本仍经本地policy→原endpoint→complete seal→原生成/审核/播放/有效ACK。

probe以后又advance或真实speech续说会撤销旧发布权限/旧raw资源（包括已detach后仍在等待endpoint的分析）；client34继续到达的speech=false静音帧不撤销当前probe，也不写越冻结N的字节；已有完整capture保留，后续真实probe等待原资源确认退出后用legacy完整snapshot。首次资源已finish后不再次提前创建；相同表达后续probe仍按原快照路径，不拼partial转写、不自动补偿失败请求。提前ASR供应商异常仍附在该lease上，由当前真实probe走既有failure分类，绝不隐蔽fallback/重试或当unknown成功。预开失败后即使多个advance仍只有原那一次预开。

成功取到raw文本时，task.done意味着其resource __aexit__也已完成；在当前Operation核验后立即detach consumed lease，随后再跑policy/endpoint。不能等_analyze finally才detach，否则空ASR→finish_input_analysis→clear_capture会自撤销当前Operation而吞掉unknown。异常完成同样先detach再进入原failure解析；真实资源不健康仍quarantine，不能借detach放宽健康门禁。空ASR、semantic unknown、endpoint发送与seal交错均有真实VoicePeer测试；正常unknown保持原scope帧+原decision字段，后续自然输入不需新wake，无ACK伪造。

## 取消、期限与资源边界

全部生产capture.clear路径集中到clear_capture，先撤销raw lease，再重置表达。stop/epoch、end/断线、management pause/resume、session/connection/turn/private变化、原TTL/heartbeat失效、原deadline耗尽均撤销。private切换在实际修改前撤销；其它归属变化在handle入口/monitor检查，并在每次I/O前后重验。route/HOME等继续由client34既有stop/断线屏障撤销，不新增协议。

取消时立即记录一个绝对0.5s deadline，writer/reader/资源退出与后续probe等待共享原deadline，不按每个await续0.5s；无合作的资源quarantine，禁止新provider，retired task继续有owner跟踪。run退出也撤销尚未probe的raw任务。正常V2Speech连接和reader生命周期不改，原resource acquire4s/close0.5s门禁保留。无跨session连接pool，无partial text/log/context提交。

不加20s墙钟截止：它会改变合法长表达/THINKING行为，当前没有必要引入。原640000字节容量、真实speech(age_ms)更新的15s预算和原THINKING排除规则不变；开连接、ready、advance、probe、finish和handoff均不续预算。未probe的raw资源最多等到原表达/会话有效边界，monitor仍检查，不用提前静音seal腾资源。

## 投机费用与调用上限

每个capture表达最多一次提前ASR尝试，不随revision增长；同时最多一个raw连接。确认资源释放前不会预开第二个资源或进入新snapshot调用。跨表达的正常请求数仍由真实输入决定，没有免费结论。

正常首probe可以消费同一个提前请求，ASR调用数不增；但在首probe之前取消、切scope或失效，会消耗原来根本不会发出的提前请求。首次probe之后续说会丢弃已消耗的早期请求，再由后续真实probe分析完整快照；相对于某些legacy时序可能多耗一次已取消任务，必须单列，不能声称费用零增长。原供应商额度错误即failure，既有endpoint/plan/facts有限read策略不改，ASR不新增retry。账单单位/取消计费未知，root决定启用前接受此取舍。

## 验证与放行

新增行为测试直接驱动真实VoicePeer.handle/run/monitor与生产recognize/write/finish端口，另用真实V2Speech和本地WebSocket验证run-task/finish-task、完整字节、reader完成和connection_lost释放；没有复制lease实现当测试替身。复用原FullProtocol/ResolutionTLS的真实ACK/played事实断言做flag-on回归，包括正常续轮、重复取消、空ASR/unknown、旧audio/ACK隔离、失败/THINKING/未强制seal。默认off原套件保留。

验证命令（重任务串行、2GB原wrapper；测试均为合成/本地，不调用供应商）：

```sh
scripts/with-build-lock python3 -B -m unittest tests.v2.test_stream_asr tests.v2.test_m04 tests.v2.test_m04_transport tests.v2.test_recognition_handoff tests.v2.test_speech_release tests.v2.test_failure_observer -v
```

完整V2是namespace目录；若用包名加载所有test_*.py，需同时将repo根与tests/v2加入本次Python进程sys.path，以兼容旧测试的unqualified imports。在root wrapper中旧Git对象测试还需仅本次进程的GIT_CONFIG_COUNT/KEY_0=safe.directory/VALUE_0=精确检出目录，不能修改全局Git信任。失败原日志与修正入口后的结果均交root，不用跳过失败换绿。

root审源码及CI后，才可在其掌管的V2启动命令显式增加 `--stream-asr`；必须保留原TLS/device-scope/credentials/check等参数。`--check`只做离线预检，不代表streaming真机成功。正式启用前不部署、不改service.env、不发provider probe、不生成APK。回滚为去掉该CLI flag并按原V2流程重启；关闭flag使用原probe snapshot路径，无数据迁移、wire变化或V1变动。若是候选源码本身需回退，由root按原release来源恢复。本文只是启用/回滚计划，作者未执行。

whole+firstsegment并行仍仅设计结论、不在本patch：成功多句可以共享同scope/context快照并行原两项，但whole拒绝路径会多花已经启动的first请求；当前不允许暗增该失败路径调用。单句只有whole、不额外审核。
