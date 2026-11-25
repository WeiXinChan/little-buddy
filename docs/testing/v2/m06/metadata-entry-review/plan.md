B 独立 metadata-only 执行接线冻结方案。当前只供 root 审定，未 push、未 dispatch、未 CI/AVD/adb/root/音源或 Android 构建。基于已审 b70a526/tree633ea35c93f3bed2e5ba5b6b33302799f838b588；PR36 HOLD。原常规 V2 workflow/global 正控文件完全未改。

## 触发可行性与伴随运行

不依赖 workflow_dispatch。GitHub 官方明确其事件要求 workflow 已存在 default branch；不能把新PR分支文件当可手动触发，更不为注册提前合入main。[官方事件规则](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)

本冻结包含独立 `.github/workflows/v2-metadata-only.yml`，只听 PR synchronize，paths严格为自身文件或 `scripts/m06/metadata_only_observation.py`；job进一步限同仓库 WeiXinChan/little-buddy、PR36、head分支 agent/agent/70f7ce4d7235。另加job条件：event.before必须等当前远端f6f63ac69909bdc4416ad5ea5def8d816d461b89，after必须等PR head.sha，run_attempt严格为1；否则job跳过，绝不启动AVD。用PR事件而非pull_request_target；checkout精确event head SHA，不在默认分支执行PR代码。root审定整个新树后，才从该既定before一次快进发布PR36 head；那次synchronize方可触发，不需先合main或二次label/盲dispatch。没有本地实际触发验证，不把文档语义当运行已成功。[官方PR语义及head checkout](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request)

本次累计新增/修改scripts/m06也匹配既有v2-eyes.yml，发布时**会自动伴随一次正常V2 JVM/assemble/mic+九门运行**；此不覆盖/跳过/缓存旧包。新metadata workflow共用 `v2-eyes-${{ github.ref }}` 顶层concurrency、cancel-in-progress=false，两run在同PR串行而非同时准备AVD；哪个先运行由GitHub调度，不宣称固定顺序。只发一次root审定head，不追加自动retry；有更新pending会受GitHub原concurrency语义影响，避免连续推送。

按当前相对已发布f6f63ac的差异，未改app/backend或android-smoke.yml及其列出的路径，因此不预期额外global run；若root合并了其他diff而触发global，则如实登记，不能隐去。global95双API SUCCESS/36 exact2 sealed2是root实核历史，本轮不重跑也不拿它当B动态结果。

## 环境/单变量与停止门

CI31/32是临时GHA job，已结束runner的PID/socket不能跨run复用。本方案复用**原环境创建方式及guard**，新建同一owned ubuntu-24.04 GHA私有目录/两个null Pulse/GUI Xvfb/API36 google_apis x86_64 AVD。没有APK构建/下载/安装，没有启动Activity/AudioRecord。仅原已批准启动参数 `-feature -VirtioSndCard`，无第二配置/格式/音量/属性变更，不要求guest先有HDA卡才可观测。

启动前sdk_support严格要求实际SDK37.3.10/build16970787、指定image API/ABI/tag与两份指定feature声明可解析，原文件SHA入证；实际guest六个getprop逐一查硬件ranchu、product、API、ABI、fingerprint13894323及simulate_input空/0/false/off。simulate_input非空真/未知停止；空值仅缺失，不证明实现默认。runner SDK升级或镜像指纹不符即STOP，不换SDK、不扫组合、不fallback。

PrivatePulse→MetadataPulseView重复验证原所有隔离条件：GHA hosted/明确serial/PID、700目录、UID/exe/祖先、owned私有unix socket、-n和指定配置、仅两个null sink/monitor、合法module/client/source-output及QEMU私有后端环境。实际host hda_projection必须唯一force_off/on0/unknown0且无冲突，只是请求证据。缺guest正HDA是本次要测的事实，不能作为metadata采集前置，也不能由host请求冒充。

## 入口与顺序

`python3 scripts/m06/metadata_only_observation.py` 仅在workflow准备身份环境后运行：

1. 显式 M06_METADATA_ONLY/M06_NATIVE_READONLY=1，安装文件门→BASE隔离scope/唯一feature-off→固定guest身份。
2. 原GrpcMic **state_only_auth=True** 初始化；匿名getMicrophoneState必须拒绝、owned descriptor/token、loopback listener及SDK版本检查沿用，只get/set false，不调用injectAudio、不调用PaOnlyMic/播放。无token/header/descriptor正文输出。SDK false实际读回。
3. **同一个NativeReadOnly实例**只调用prepare一次，显式metadata_proof=view：原单次adb root(≤8秒)、wait-for-device(≤8秒)、id0、HAL PID/UID/starttime/exe/白名单objects及原prepare证据。权限/身份失败即STOP，不第二次root/重新attach。沿用prepare现有只读snapshot和enum日志投影，不扩全文读取。
4. 成功后调用enumeration_metadata(metadata_proof=view)：原共享8秒deadline、逐项typed ALSA、kernel release/audioPCI/卡关联。前后guard/object复核；数据未知仍保存具体状态，身份失败标不可关联。此API不进入runtime_gate/arm，所有输出fixture=NOT_RUN、fixture_authorization=false。metadata未知不强造HDA证据；HDA未知仍对产品fixture STOP。
5. 所有查询owned子进程由bounded回收后，finally set false并get实际false，关闭gRPC channel；外层trap TERM→有界wait→必要KILL→有界wait并回收精确owned emulator/Xvfb/Pulse PID。没有observer/parec/paplay或采样线程。cleanup失败单列并使job失败，不能盖掉主reason。未到SDK初始化的早停记sdk_final_false=null，不宣称读回成功；随即销毁本job owned环境。

## 预算与证据

新workflow job总上限12分钟；setup SDK/软件包遵循平台有界job，boot wait-for-device180秒+boot180秒（沿原范围，无重启）；SDK/proto严格guard不放宽。Python采集段单次75秒alarm、外部90秒TERM+5秒kill-after上限，允许既有root8/重连8/prepare旧snapshot8等固定阶段，**不改变B snapshot的8秒**或任何产品TTL。alarm/TERM转固定reason使finally尝试false；异常强杀不能证明false，必须按缺证STOP。owned环境最终被trap销毁，不能当可持续服务。

证据仅 `render/metadata-only/` 的sdk文件hash/prepare/白名单对象及enum metadata/result阶段时间与安全class/reason/固定项目栈；原匿名拒绝/loopback初始化journal和ready投影另存。无emulator完整日志、raw env/cmd/config/PCM、APK、音频或任意异常消息。失败同样upload，缺对象/权限/截断/超预算按原枚举，不补猜。

结果名明确 **OBSERVED_NOT_PRODUCT_PASS**，不是HDA或麦克风PASS。exit0仅表示身份复核/最终SDK false的观测完成，可含NO_SOUNDCARDS/EMPTY/UNRECOGNISED；逐项未知不得当支持已证。exit1包括早停/身份或false缺证。主观测与产品V2/global CI分层汇报，原mic门不降级。

## 本地验证边界

新增纯mock入口负控：BASE/唯一feature-off失败在控制器/root前停止；prepare失败只一次、不enumerate；成功只set false且最后读回false；最后false读失败为STOP；未知观测不赋fixture权限。既有真实verifier+模拟OS/拓扑接线负控保留。YAML parse、每个run的bash -n，只检查语法；所有设备/控制器由mock替代。未运行workflow setup命令或此CLI真实入口。

方案冻结后交root精确tree；仍需明确发布/执行放行，不能因代码审过自动执行。没有用户待办。

最终本地结果：RequireHDA=1及CI关键env完整host suite107 PASS（原102+入口5），所有run段bash -n、YAML parse、git diff --check PASS。常规V2/global/生产目录相对b70冻结diff为空。actual GHA/SDK/PCI/ALSA结果仍NOT_RUN，不将mock控制当实机观测。


## 一次发布绑定收口（取代仅paths的一次性假设）

PR paths是累计diff，因此paths/branch不能单独证明一次。本冻结以特定before→after transition及attempt=1为门，后续普通push的before已不是f6f63ac，手动rerun的attempt>1，均在job if就跳过。checkout fetch-depth=2后第一个step用同CLI `--publication-gate`读取≤1MiB GITHUB_EVENT_PATH，仅解析所需固定字段，不落完整payload；核事件名/动作、仓库/PR/分支、before/after格式、after=head.sha=checkout HEAD、实际git唯一parent=before。不符exit1且无SDK/AVD/setup。实际观察CLI开始还重复该纯本地门，不能绕过第一步。

[Octokit的GitHub pull_request synchronize schema](https://raw.githubusercontent.com/octokit/webhooks/main/payload-schemas/api.github.com/pull_request/synchronize.schema.json)明确requires before/after；这里用实际git parent关系校验其发布语义，不用merge GITHUB_SHA代head，也不假设所有GHA payload必有字段。运行时字段缺失/未知即STOP，不补猜、不再盲触发。没有读取真实新事件或实际dispatch。根审定发布必须以现远端f6f为parent的单次快进，禁止为重新满足条件reset/force回旧头；若远端先变，旧授权自动失效，交root重新决定，不改常量凑过。

两workflow共用原V2 concurrency且cancel=false，不相互取消running；有且仅此次两run时一running一pending串行，实际先后不保证。第三个事件可能按GitHub原pending语义替换pending，故本方案不额外push/retry；诊断后续无关push/attempt2不分配observe job，不能靠累计paths再启动AVD。伴随普通V2/global触发清单仍按上文，不削常规测试。

新增发布门纯函数负控含正确transition、缺before/after、不同before/after、错误动作/分支、attempt2/0/空/None、parent不符；没有root/AVD/设备调用。最终完整host108 PASS；YAML和每个run bash -n再次通过。此前107日志结论仅属前一草案，最终冻结使用108结果。
