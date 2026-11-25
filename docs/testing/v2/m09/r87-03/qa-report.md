PR40 R87-02 独立定向复核：原问题修复通过，新增 R87-03 阻断，暂不建议合并。

固定 base 77893453fa855eb31838ce506fa36b6debe9a696；head 126d1d36928a6f1e2c25c936814f7218810830b6；tree 4188a2cf12be8c4ef5d1e40c3e76e52a8c6cc598。本轮 ls-remote 确认远端 head 相同。相对 base 31 文件；相对上一 head，产品仅 FeedbackEngine.kt/FeedbackPageFactory.kt，Core/Vault/Contracts/授权与 Android runtime 未变。原 QA 探针逐字节保留，原 QA 证据包与缺 SDK 原件未改。

实际分母
- 正常套件：79 执行/79 通过/0 失败/0 跳过，exit0，含原 R87-02 断言及11项新回归；实际编译全部 feedback/parent 和 Android 页面/JobService API。
- 独立追加异常路径：1 执行/0 通过/1 失败/0 跳过，编译exit0/JUnit exit1。
- 本轮正常场景合计80执行/79通过/1失败/0跳过。
- 负控：10种分别实际编译成功，各执行1断言、1预期失败、0跳过；10/10有效，聚合命令exit0。trace均为预期 AssertionError，非编译失败。
- 历史68执行/67通过/1失败和作者旧源同原断言1失败留在原包，不混入本轮正常或负控分母。

R87-03（阻断）：到期 sweep 存储异常时，待投递过期详情仍可回放。
复现使用真实 PrivateVaultFiles + AES256 vault，合成时钟/页授权/provider，以及可阻塞投递的串行worker/UI队列。先提交合成正文；原提交+7天前1ms打开新有效页并完成detail worker，暂不执行UI；推进1ms到截止等值，VaultFiles.replace 注入 IOException；执行 sweep 返回false。取消故障后以新 Core 重开同一实际vault，list为空，证明已到期。随后放行旧UI队列：旧 Detail（description非null）先渲染，之后才 Notice(STORAGE)，新断言因此失败。测试没有改变产品代码。

根因位于 FeedbackEngine.kt:58–66：失败发生在 afterSweep 前，catch 分支仅排队 Notice，未清 pending/推进旧version；先前run闭包在47–49仍匹配，deliverPending(97–99)交出旧screen。成功路径79项不能覆盖此异常。最终notice不抵销先前过期正文回放；原生渲染收到Detail会建立正文控件，但本次实证止于实际engine render回调，并非Android设备屏幕。

交原519修复：异常路径也须及时释放敏感pending并使旧投递失效，错误通知不得覆盖后来编辑/新页面；保留本探针原断言，补失败/取消/迟到路径。不得仅弱化断言或只验证最终Notice。

成功路径评审：tick对详情/列表按version重读实际core，清待投递槽；闭包只携版本，后续编辑/页面更替用CAS与epoch隔离。期限前1ms/等值、回复、重复tick、日志先到期、较早撤回、本地清副本等回归通过。原R87-01、300ms阻塞撤销、合法提交/outbox和默认拒绝未回归。页面递归清空TextView/EditText并解绑点击，源码/API编译核验通过；不声称JVM String字节覆写或真实控件/屏幕运行。

边界：API jar SHA256 7123df2cceaebc66f3991a480964968c9d9603f6abd542ea8878c39db70fcb07；不是APK/真机Keystore。作者与QA旧Gradle缺SDK失败原件保留，资源未变，按要求未重复同一失败构建。未跑CI/手机/Mac/模拟器，未部署/合并；全部重型运行串行经heavy.lock。
真实Grant acceptProtected、主入口/工厂装配仍缺；合成授权/provider不证明真实跨设备绑定。完整M09/A24–A31/D02D06、真实provider全副本删除、归属恢复/可信时钟/设备绑定、OS重启调度/音频/真机Keystore继续OPEN，自动done禁用，root最终审合。
