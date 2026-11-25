# R87-02 详情/列表到期缓存清理

修复对象为原PR40、旧head `c0f3e38b853e3090c8c98e9d76cdcbc916a80101`（tree `d84aa1bc993e2288ae70c4b50dac4629c27cdc40`），仍以main `77893453fa855eb31838ce506fa36b6debe9a696` 为PR base；不混M08 parent/host树。

## 失败与修复

旧正常67项PASS未覆盖详情过期；独立QA补充后为68执行、67通过/1失败/0跳过。QA原报告、原失败日志/JSON和探针字节原样保存在本目录；同一探针另加入正常测试为Review40Probe.kt，原断言未改弱。

原afterSweep只检查预览token，详情token为空就返回，真实vault已删除但UI仍显示旧正文/回复。现在worker仅记录展示模式、ID、版本，不缓存FeedbackView。每次成功sweep对详情/列表按同一版本原子轮换展示epoch，清空未投递快照，并从实际核心重读；单已删除返回空列表，日志先到期则重读详情范围。刷新仍经当前页授权，不借新页Grant；系统本身擦除不依赖PIN。后来的编辑/导航已变版本时旧tick放弃刷新。

UI排队闭包只携带版本，不持正文快照；单个可清空pending槽在编辑/pause/retire/tick时释放，投递二次核版本与页面。原生重绘/离页显式清空TextView/EditText并解绑旧点击回调，移除旧详情/回复引用。JVM不可变String不承诺字节覆写；此处为引用释放与控件清空，非堆取证或OS显示实证。

保留原核心/授权/工厂契约：不改FeedbackCore、Vault、ParentDomain、Provider与最终授权事务；R87-01、300ms阻塞IO撤销、合法决定后的事务结果、outbox与默认拒绝仍由回归核实。主入口与真实acceptProtected仍尚未装配；API编译不代表APK、Keystore/OS重启调度或设备运行。原Gradle缺SDK失败不改写、不反复重试同一缺失资源；完整M09/A24–A31/D02D06及真实平台全副本/归属恢复/时钟绑定等继续OPEN。无Mac/手机/模拟器/HDA操作，heavy.lock全局1。

## 新增反例范围

除原QA不变断言，新增11项：新有效授权在截止前1ms/截止等值/重复tick与回复；列表缓存；尚未投递的详情及列表；无家长页面；授权撤销；tick刷新后编辑；tick排队后编辑；旧页关闭/新页切换；日志范围先于说明到期；本地清副本与较早撤回截止。均使用真实文件/AES-GCM和实际引擎，合成时钟/Provider/页授权，不以provider spy代耐久材料路径。

负控新增恢复token为空直接返回的缺陷，执行同一Review40Probe原断言；原9负控继续独立编译运行。迟到UI负控随投递槽重构调整为直接捕获/投递旧快照（移除版本及当前页重验），仍运行原断言，防止只测一个失去效力的文本替换。实际分母与命令另见本目录最终日志/JSON。

作者本轮另用 --source-ref c0f3e38 固定生产源码、--case Review40Probe#systemSweepMustRetireDisplayedExpiredDetails 执行原断言，实际RESULT 1 1 0、exit1；原始记录为old-author-reproduction.json/.log。它是历史缺陷复现，非本轮正常通过或突变检测。共享锁exit75的尝试没有执行测试，不计分母。

## 正常回归

本轮实际79执行、79通过、0失败、0跳过，exit0；原67项 + 原QA反例1项 + 新到期流程11项。源码与测试SHA-256逐项核对匹配baseline.json。包含真实feedback/parent源码及Android工厂/JobService/页面API编译；单worker、真实文件/AES-GCM，合成时钟、Provider与页授权。原UI验证目录记录的是历史67项，不能用其覆盖QA后68项的1失败或本次79项记录。

```sh
scripts/with-build-lock python3 scripts/test-m09-core.py --source-ref c0f3e38b853e3090c8c98e9d76cdcbc916a80101 --case Review40Probe#systemSweepMustRetireDisplayedExpiredDetails --out build/m09-core/r87-02-old.json
scripts/with-build-lock python3 scripts/test-m09-core.py --android-jar "$ANDROID_API_JAR" --out build/m09-core/r87-02-baseline.json
scripts/with-build-lock python3 scripts/test-m09-core.py --negative-controls --out build/m09-core/r87-02-negative.json
```

API jar SHA-256仍为7123df2cceaebc66f3991a480964968c9d9603f6abd542ea8878c39db70fcb07。原作者Gradle失败保留在../ui/gradle.log，QA独立12s缺SDK失败另保留old-qa-gradle.log；本轮资源未新增，不再次执行同一个已知缺SDK命令，也没有APK/设备运行证明。

源码检查（排除原始日志）通过；原始Gradle日志尾空白按原件保留。旧head复现只编译该历史生产源码和同一QA探针；最终正常API编译覆盖当前全部feedback与parent生产源码和全部测试。

## 最终负控结果

10个突变全部独立编译成功，各实际执行1个断言、预期失败1、跳过0，10/10检测有效（主命令exit0表示检测有效，非子断言通过）。新增expired-detail-cache恢复token为空早退，命中Review40Probe原R87-02断言。完整trace与最终源SHA-256见negative.log/json，原9项回归保持有效。

| 分母 | 执行 | 通过/检测有效 | 失败 | 跳过 |
|---|---:|---:|---:|---:|
| 旧head作者原断言复现 | 1 | 0 | 1（原缺陷） | 0 |
| 新head正常回归/API编译 | 79 | 79 | 0 | 0 |
| 新head独立突变负控 | 10 | 10检测有效 | 10预期断言失败 | 0 |

测试不证明Android控件实际渲染/堆擦除或OS调度、平台/真机效果；这些限制与未装配工厂/Grant边界保持原样。待原QA按固定SHA/tree独立复核，root审合；本作者不合并。
