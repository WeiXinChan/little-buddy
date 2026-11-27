# 续说后旧识别阻塞：受控复现与有界交接

本业务PR的实际base是冻结PR152 `1c508d5bd9273734579b44e5f90181e4d87bad66`（base branch agent/tita-87-stage-timing），保留全部计时hooks。最初在main af46独立工作树用真实VoicePeer复现并形成未发布checkpoint，再安全cherry-pick到该base；未修改/强推PR152。待152合main由root retarget。本变更不在服、无云/手机/部署，无V1/Android变更。

## 已证因果及边界

旧VoicePeer advance只清analysis/prepared并更新revision，不撤销recognition。真实handle(probe rev1)→受控endpoint可取消阻塞→handle(advance rev2)→输入续段→probe rev2，第二次识别始终挂next_probe，必须等旧endpoint。原断言期待新probe在150ms内进入，实际TimeoutError，原FAIL保留；fixture在finally显式放行/回收，无孤儿。旧scope已安全失效不等于失效任务不占性能路径。

同一输入/断言修后PASS，旧endpoint在没有被手工放行的情况下取消，新revision得到endpoint；本地合成整项约9ms只证明解除受控等待，不是手机/供应商延迟，也不解释code31的额外差分。原唯一真实probe source8e22结果不改，此阶段新增真实调用0。

## 最小实现

advance立即撤销旧recognition operation并cancel旧Task，建立一个独立handoff owner并纳入retired管理；输入owner不等待释放，只保留最新一份capture快照及其新Operation。观察截止从取消请求时刻固定为原0.5秒，不按反复advance/probe续期。使用asyncio.wait，不把wait_for等吞取消当硬截止。

只有旧Task终结、无资源quarantine、handoff/recognition指针仍归自身、原Session对象/id/connection/epoch/private不变、最新Operation revision仍有效时，才创建新的_analyze。新任务绑定新权限，不复用已撤销operation。反复advance清旧候选，新的probe只替换一份待处理快照；测试见证原640 bytes输入段和两次续说全部保留到新1920bytes快照，没有截断尾音。

旧_analyze finally在独立handoff存在时不得消费next_probe；旧owner也不得清掉替换owner的候选。cancel_recognition将旧Task与handoff在同一个原.5s窗口内收尾；caller取消或helper观察被取消而无其他owner接管时，未确认即隔离/保留句柄，不启动新供应商。吞取消、close失败/未确认同样隔离；不承诺物理杀停任意stubborn协程，既有server quarantined实例拒绝复用，最终进程隔离由原部署监督负责。

Operation仅额外捕获private_mode供识别入口/发布及handoff校验；不改变PLAN合法private transition权限。所有原endpoint/轮次/安全语义、共享retry计量及15秒表达budget保留；advance不新建/续期ResponseBudget，也不自动probe/seal或换供应商。被取消的旧请求可能已计费，仍由原供应商计量保留，不退款/重置计数。

## 离线证据

- 原FAIL输入/断言未改，修后正控通过。
- 释放前不得启动新识别；高频advance/probe仅最新revision3发布，capture完整。
- endpoint吞取消、ASR close失败和未确认在原界内quarantine，不开第二provider。
- Session/connection/epoch/private替换不得沿旧handoff开新调用。
- 旧finally晚到不消费新owner候选；取消收尾调用方/直接取消handoff观察者均不允许未确认连接复用。
- 原15秒输入deadline跨过但TTL/heartbeat受控保持有效时，新识别仍不发出；deadline值不变。
- base152同生产路径组合105项PASS（含R99、共享retry、TTL/stop、M05、安全与V2资源释放、计时/61块loopback driver）。使用全局with-build-lock/MemoryMax2GB。之后收紧直接helper caller取消隔离，定向handoff+timing/driver再29项PASS；有重叠，不将其累加充当独立样本量。
- 首次组合因历史test_r99使用顶层test_m05导入而报ImportError，保留日志；按既有tests/v2模块路径运行后通过，没有修改/skip原R99负控。

命令：
```
bash scripts/with-build-lock timeout 75s env PYTHONPATH=tests/v2:. /usr/bin/python3 -m unittest tests.v2.test_recognition_handoff tests.v2.test_stage_timing tests.v2.test_stage_probe tests.v2.test_r99 tests.v2.test_read_retry tests.v2.test_session_expiry tests.v2.test_stop_idle tests.v2.test_m05 tests.v2.test_speech_release
```

本次仅独立源码缺陷证据与离线业务修复，等待root/QA审合；无P12达标、真实供应商cancel分支或手机效果声明。
