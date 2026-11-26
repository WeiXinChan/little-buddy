## 供root审定执行的V2后端发行方案

本批显式依赖PR51 36375242b28fb945c5ef26ce4b7f38932c197ba4；不修改V1或Android/host/parent。这里的安装/启停命令是获准后的执行方案，本次均未部署执行。仅真实loopback合成验证，不代表家庭网络/生产可连。

### 发行和匹配

`python3 -m backend.v2.release package --ref <固定40位SHA> --output <新文件.tar.gz>` 从指定Git提交打包，不夹带工作区未跟踪文件。包含V2后端及所需共用Python模块、完整60 PNG/清单、V2 systemd/控制脚本/配置例、完整默认依赖闭包的精确版本锁；不含密钥、设备材料、V1配置或Android代码。tar/gzip固定顺序/mtime，生成release-manifest.json：source_sha、每文件hash/大小、原协议与模型。对外传输SHA256由root对照本次交付值，包内清单本身不是签名或家庭归属证明。

匹配APK必须由b30固定制品确认支持：wire v2，safety1本地帮助、images2有界PNG传输及ACK揭晓/定时隐藏/延长再展示、volume1本次语音调音量、management1同连接暂停退出与scope、end1会话结束；契约ID `v2-voice2-safety1-images2-volume1-management1-end1`。preflight要求显式`--apk-contract`与scope内protocol_contract一致；这只是版本匹配声明，不声称读过/验过远端APK。旧wire兼容不等于旧APK满足本发行完整功能。

### 准确启动条件

- Linux/Python≥3.11、OpenSSL可执行文件、systemd及已审核wheelhouse；`backend/requirements-v2.lock`锁websockets/httpx及全部默认传递依赖，prepare逐项核已安装版本。不是联网安装器，包不含wheel；root需从已批准缓存/源备齐精确wheel，不能默认改版本或新开付费服务。
- 固定发行位于`/opt/little-buddy-v2/releases/<SHA>`，root持有、目录0755/源码0644，内有独立`.venv`。root可离线`python3 -m venv .../.venv`，再`.venv/bin/pip install --no-index --find-links <受审wheelhouse> --no-deps -r backend/requirements-v2.lock`。不借V1虚拟环境或改V1依赖。
- `/etc/little-buddy-v2`为root:root 0700，所需输入均root:root 0600的普通单链接文件：service.env、dashscope-api-key、v2-device-token、device-scope.json、tls-certificate.pem、tls-private-key.pem、trust-anchor.pem。不得把V1 token当V2凭据；例文件不含有效token、默认过期。scope是操作人员绑定本V2 endpoint/新token哈希/截止/协议的运行配置，不是OwnerProof或家庭绑定记录。
- systemd通过LoadCredential提供动态非root用户可读的只读副本；不把root 0600源直接交给非root进程open。证书须有回环IP SAN 127.0.0.1，私钥匹配，trust-anchor须是受审信任链；OpenSSL离线验链/名称/用途/期限。该证书仅证明后端回环TLS腿，公网入口证书/代理上游校验与APK信任仍需root独立核实。
- ASR/TTS仍固定Fun-ASR、CosyVoice-v3-flash/longanyang；V2文本新安装默认deepseek-v4.1-flash-1017，仅允许显式选择该快照、deepseek-v4.1-flash或qwen4-max，无自动付费/跨模型回退。视觉提示/图片审核独立固定qwen4-max。DASHSCOPE_LLM_MODEL必须显式配置，旧已配qwen4不会被代码静默覆盖；omni/未知模型拒绝。Flash请求JSON Object、nonthinking，并由本地严格验证；只qwen4使用既有json_schema模式。模型构造校验不调用供应商，不证明账户免费额度或账单。

### 检查、启动、停止与回滚

1. root先对照交付SHA256，审包内路径；将包解至上述新SHA目录，root所有权与非可写给服务用户的权限；离线安装锁定wheel。后续`.venv/bin/python -B -m backend.v2.release verify --directory <SHA目录> --ref <SHA>`核正文、缺失/额外文件和版本；不把任意未核tar交给root执行。发布树不可挂其他代码，运行使用-B不生成源码缓存。
2. root准备V2专属运行输入（不从聊天接收密钥、不生成OwnerProof）。可在既有授权范围给V2映射受审的供应商/回环TLS材料，须保持V1源与配置不动；本模板默认使用V2目录内受控输入，具体授权由root核。`python3 backend/deploy/v2-control.py check <SHA>`默认只输出计划；`--apply`才以root读取实际配置进行离线preflight，无网络/监听。字段/类型/权限/版本错误均只出固定码，不打印路径、密钥或完整环境。
3. 将`backend/deploy/v2-little-buddy.service`审定安装为`/etc/systemd/system/little-buddy-v2.service`，真实执行`systemd-analyze verify`及daemon-reload前需root批准。模板固定回环19483、无特权capability、256MB/无swap/core、DynamicUser/LoadCredential、受限日志；ExecStartPre先核选中SHA清单再核实际配置；Type=notify仅在TLS回环绑定后发READY=1，避免把进程刚exec就当启动完成。本次仅替换可执行路径做临时语法验证，未安装单元。
4. `python3 backend/deploy/v2-control.py start <SHA> --apply`：先完整检查目标发行/当前V2输入，成功才停止V2旧单元、原子切current、启动并核is-active；不接触little-buddy-v1。启动失败留明确failed_closed，不自动恢复旧凭据或冒称回滚成功。ready_loopback只是绑定完成，非公网健康或模型可用。
5. `... stop --apply`仅停止V2单元；SIGTERM/SIGINT进入server上下文关闭，活动会话/任务清理。回滚用`... rollback <受审旧SHA> --apply`，重新验证旧包和当前V2配置/协议/截止，停止后原子切换并启动。不复制旧token/旧环境，不恢复已过期或撤销授权；契约不匹配的旧APK/发行不能回滚复活。

监听固定127.0.0.1:19483 `/v2/voice`，TLS≥1.2，认证Bearer是独立V2设备token。scope not_after在启动、握手及活动连接执行，到期拒绝新握手并清活动Session；使用服务器系统时间，不冒充设备可信时钟/远端家庭归属。撤销/轮换仍先停V2单元再替换当前输入，禁止在旧实例继续运行时仅改磁盘文件宣称撤销生效。无公开入口/反向代理变更由本脚本自动完成。

### 最小实测

tests.log为新增10方法（正常9＋权限门槛负控1）和原配置/审核503抽查3，合计13执行/13通过/0跳过；不是全套QA。真实CLI子进程的loopback TLS/auth/scope/pause/resume/坏帧安全日志/SIGTERM，以及活动凭据到期清会话/新握手拒绝通过；没有儿童音频、供应商推理或真机。Python编译与diff检查通过。systemd-syntax.log仅临时单元替换可执行路径的语法验证exit0，不是生产安装/启动证明。发行包实际固定head打包/重复hash/解包verify结果在交付评论及package-check.json。


部署接线补充：默认unit与v2-control现同时传入image-config和feedback-database，详情与首装父目录步骤见`docs/testing/v2/deploy-inputs/README.md`。root源0700/0600与DynamicUser只读credential副本语义不变。反馈状态在`StateDirectory=little-buddy-v2`下真实0700的feedback子目录；离线root预检不建目录/数据库，首装先由root准备父目录。默认不声明single-store-no-exports-v1，all_copies_deleted不能由单库删除推断。此前版本发行包不包含此接线，须由root从最终已合SHA重打包再审定启动；本批没有部署。


免费图片策略补充：root审查后可使用`backend/deploy/v2-image-free.example.json`切换2.1 Turbo优先/Pro后备（新增fallback_model、free_tier_only，专用key/政策ID与qwen4-max审核不变）。配置声明须对应两模型控制台用完即停，不是账户余额证明；不自动付费回退3.0。具体URL隔离、严格quota后备/双耗尽停止和有限真实单图验证步骤见`docs/testing/v2/free-image-routing/README.md`。旧实际image.json不会因部署代码自动改动；不据本地计数宣称免费，qwen-mt-image翻译额度不用于生图。按含适配的最终main核后端发行清单，RC8/APK版本无需为本后端改动变更。本批仅本地合成验证，未部署或真实推理。

文本模型发行身份补充：release-manifest.json的models列默认1017，model_policy列精确允许文本集合、独立qwen4视觉审核、JSON格式、nonthinking与无自动fallback；runtime检查报告的models仍反映实际配置。打包器须从相同models.py的固定源码SHA运行，拒绝用新默认身份标注旧源码；verify检查model_policy身份及源码inventory。只改受控V2 service.env的一行文本选择，image.json/review key/图审模型不随之切换。最终切换由root完成更多语义/审核效果后决定，本批作者未部署/读取真实配置。
