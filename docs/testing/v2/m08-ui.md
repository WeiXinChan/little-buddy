# M08 原生管理页与真实Grant本地接线

固定源码基线 `77893453fa855eb31838ce506fa36b6debe9a696`（已合PR38/39）。
隔离目录 `tita-86-8c4eebd1bbc1/workdir/little-buddy`；新分支 `agent/tita-86-parent-ui`。
不修改M06诊断树、V1或feedback包，不创建/修改它的JobService和manifest。

## 当前交付

- V2日常画面为Canvas两眼，不显示常驻管理/调试按钮或凭据状态文字。右下角长按
  900ms仅请求验证页，无PIN权限。`requestParentManagement`为未来管理事件的明确
  本地接入点；目前只有audio owner确认voice/capture均无且未隔离时才挂载页面。
  活跃语音拒绝进入，不将close/reconnect伪装成管理暂停、保留会话或零上传证据。
- 原生验证、设置、改PIN控件调用ParentPanelModel，再调用已合ParentDomain。
  模型仅保存真实Grant引用，不以accepted Boolean授权。六位ASCII PIN、前导零、
  限次与持久冷却均由原域决定；正常PIN修改需旧Grant，慢哈希/落盘前重新验权，
  成功后撤销全部旧授权，保留音量上限/不触配对，使用新PIN重新验证。
- UI/IO分离：AndroidParentPanel单worker处理加载、KDF和保存；UI Handler仅显示
  经过revision校验的结果。每次原生视图构造有独立viewToken，旧按钮不会借用新Grant。
  HOME/onPause、失焦、destroy、取消退出先原子失效本host的页，再清输入/子页和音频
  收尾；旧host重复销毁不误伤更晚host，旧任务/旧回调不能恢复授权。
- 500ms检查闲置期限，轮询和后台事件不续期；实际本地触摸/保存/导航的有效操作
  可以续期。过期即锁定，即使后台保存还在进行。队列中的PIN数组在失焦/退出立即
  清零，域和模型finally再次清零。取消/退出回两眼待唤醒，不自动收音/续播。
- FLAG_SECURE实际设置于V2窗口；PIN控件禁保存、autofill、个性化学习、选择菜单/
  长按粘贴，仅数字密码键盘；使用TextUtils复制到CharArray后立即清Editable，不建
  PIN String，不读取Intent extra/剪贴板。异步异常只显示类别，不打印异常正文或秘密。
- 父域新增acceptProtected，最终点重验真实Grant/page/generation/冻结期限及CAS后
  见证，随后同步执行具体短内存decision。供M09保护staged publication/admission，
  不跨IO缓存Boolean；异常定向撤销旧页，不能恢复权限。nextPage在内部路由轮换Grant
  并保留deadline，旧页权限立即失效，连续管理不因正常导航重复输入PIN。

## 默认拒绝与真实能力缺口

`AndroidParentRuntime`尚无审定的可信device binding来源，返回未配置。未来只有
已验证绑定才可在worker调用AndroidParentDomain.open；不生成安装ID冒充归属、不接
调试extra或测试OwnerProof。生产首次设置/系统恢复因此不可用，页面显示明确原因，
不能儿童抢设PIN、万能恢复或删除配对。本轮只是可信提供者缺失时的拒绝与可接线页面，
不能宣称设备归属/真实登录已验证。

M09提供的FeedbackPageFactory/FeedbackGrantGate/handle签名已定向交接，详见
`m08-route-contract.md`；M08拥有host/parent，M09拥有feedback页面/域与调度。
本PR提供ParentFeedbackRoute端口，默认PendingFeedbackRoute不挂载未合页面，显示
“帮助与反馈尚未接通”；两支审合后依赖PR适配实际工厂。不是已集成反馈UI的声明。

主线VoiceClient当前没有已合管理事件、原生提示watermark/上传门控桥。仅完成闲置状态
的本地验证页入口，真实多语音表达、活跃会话管理暂停/恢复及音频零上传仍OPEN。
音量上限安全落盘已接，播放执行侧未接，页面如实说明接通语音后生效；语速/已验证
音色、端点凭据、真实归属/系统恢复、OPPO/IME行为与A27/A28/A34、D04仍未完成。

## 验证边界

JVM用例调用实际ParentPanelModel和真实ParentDomain/Grant/慢哈希。仅测试文件使用
合成OwnerProof、内存存储与可控队列/时钟，不进入生产装配，不能证明实际归属能力。
测试覆盖未配置拒绝、未验证写入、原生页面动作所调用的权限门、旧按钮/路由/loader/
验证回调、HOME/取消/销毁、闲置、冷却、PIN清理/修改、最终撤销与到期，保留历史
R86-01/02/03反例与旧失败日志。真实Android窗口渲染、触摸/IME、安全截图、物理
HOME/锁屏、Keystore掉电及目标设备性能未执行，不记为通过。

实际命令与最终分母在本轮任务交付评论登记；运行使用现有heavy.lock，重型串行。
Mac/手机恢复不是本轮前置；没有派Mac、手机、模拟器麦克风/HDA或云服务。Android
编译复用既有Linux SDK和Gradle缓存，离线、--max-workers=1；无APK分发或部署。

## 本轮作者实测（2026-11-25）

- 最终父域/模型正常JVM **92/92，失败0、跳过0，127.869s，退出0**：原63＋新增
  ParentIntegrationTest 13＋ParentPanelModelTest 16。原Grant/期限/限次/密钥/IO反例
  与新页面调用链同跑；原90项通过125.956s为补充最终宿主/后台续期反例前的中间结果，
  不累加为182项。模型测试用真实Grant，不等于实际Android渲染测试。
- 完整应用模块 `:app:compileV2DebugKotlin` 离线、`--max-workers=1` 成功，最终39s，
  17任务中1执行/16缓存；包含最新PIN显式密码遮罩、返回手势及生命周期接线。此前
  40s/43s为中间编译，不重复算独立通过分母。只有旧API onBackPressed的弃用警告，
  非编译失败；Android13+另有OnBackInvokedDispatcher路径。本轮未assemble APK。
- 四类突变均只改临时源码副本，编译成功后命中预期失败：expiry 2项中1失败
  （2.762s）、revoke 2项中1失败（3.257s）、key-loss 11项中2失败（4.626s）、
  stale-view 16项中1失败（22.067s，精确命中旧按钮借用新Grant的反例）。JUnit退出1，
  脚本核对预期后退出0；单列负控，不覆盖正常集合与历史真实失败。
- PIN/材料没有日志输出；静态检查确认新UI无Log/println/异常正文、Intent extra或
  PIN String提取。音量整数的toString不是PIN。历史R86-01/02/03失败归档未修改。

复现主体命令（共享锁空闲时可直接用仓库wrapper）：

```sh
scripts/with-build-lock env PARENT_ANDROID_JAR=/home/ubuntu/.gradle/caches/8.13/transforms/9ec1aa52f1567b6bf359cfb66d138a5b/transformed/android.jar python3 scripts/v2-parent-tests.py
scripts/with-build-lock env ANDROID_HOME=/home/ubuntu/multica_workspaces/titan-q0u7-aa9ba699e3d3/tita-84-70f7ce4d7235/workdir/oppo-sdk ANDROID_SDK_ROOT=/home/ubuntu/multica_workspaces/titan-q0u7-aa9ba699e3d3/tita-84-70f7ce4d7235/workdir/oppo-sdk ./gradlew --offline --no-daemon --max-workers=1 :app:compileV2DebugKotlin
```

第一条分别追加 `--r86-expiry-negative-control`、`--r86-revoke-negative-control`、
`--r86-key-loss-negative-control`、`--ui-stale-view-negative-control` 为四类负控。
本机SDK仅只读复用工具目录，不编辑M06仓库/诊断树。一次Gradle尝试因共享锁占用
返回75未启动构建，未计为测试跳过。随后实际前缀使用运行目录中的wrapper副本
`bash ../with-existing-build-lock`，仅把`flock -n 9`改成`flock -w 45 9`以等待同一
管理员 `/var/lock/little-buddy/heavy.lock`；根权限检查/cgroup/内存限制均不变，没有
第二把构建锁或仓库wrapper变更。四类负控通过小型运行目录脚本依序调用，始终重型1。

本轮最终控件小修由最终Gradle及负控的SDK编译覆盖；92项是父域/模型调用层的执行
证据，不能替代控件渲染、键盘/遮罩/安全截图、真实HOME/锁屏的设备执行。没有真实
儿童或手机验收，A27/A28/A34、D04及完整产品继续OPEN。
