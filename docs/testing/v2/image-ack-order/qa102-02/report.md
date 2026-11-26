# ACK102-02：最终quiescent drain结果观察

原8123756已修ACK102-01，不重复实现。最新QA33项32PASS/1FAIL已冻结，原adjacent.py/review和日志逐字保留。原反例：真实已完成失败Task.add_done_callback(peer.track_retired)在cleanup最终sleep(0)注册，旧helper保留task但未result，raised=null/observed=false/cleanup_confirmed=true。相同输入/assertions本地before.log原样FAIL。

最小修复仅fixture：统一observe_done，常规收集、quiescent yield后的收集和最终收集都观察所有新完成任务；如果任务/结果集合变动，继续同一原deadline的drain，直到没有新增任务/结果。无pending不再直接当成功。首异常及句柄保留，异常原样抛出，未quiescent明确失败；confirmed只能在无pending/无错误/已quiescent/非quarantine时置true。原动态retired/visual逻辑、2秒总deadline、负控保留句柄、正常退出不重复cancel都保留。

原QA反例修后FixtureFailure被抛出、retained/observed=true、confirmed=false。QA adjacent2PASS（含隔离状态边界）；原ACK102-01原样1PASS（stubborn是明确失败、finally自行释放）；模块31PASS（原30＋健康迟到done任务1正向对照），合计34唯一PASS/0FAIL/0SKIP，编译/diff通过。原方法/assertions未改。原397绿仅历史，本轮未跑旧全集。产品源码/预算0变更，无云/手机/部署/子agent。
