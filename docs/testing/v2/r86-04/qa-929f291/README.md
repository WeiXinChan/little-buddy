QA 原始冻结证据，来自 Multica 评论 01a21218-5617-760c-bd42-21bb0e3591a9；未经修改。

旧 head 929f2919c2767b7174f6ede5d23141317558319e：正常实际17项，16通过、1失败、0跳过；三类负控另计。report.md、evidence.zip、MountFailureTest.kt、mount-failure.log 均逐字节保留附件原件。zip 中含13组合输出、QA3项源码/输出与恢复反例源码/输出及构建/签名记录。

原 MountFailureTest 调用的是已撤下的前台错误处理序列 slot.close(); model.pause()，其断言失败必须保留，不能改成通过。后台 pause 仍应 inactive，不能为了让这段旧调用序列通过而放宽拒绝。

修复版正向回归使用真实 host 与测试共用的 slot.mount → model.routeFailed，并原样保留该反例的 VERIFY、LOCKED、取消 accepted=true 三项断言及原提示；改变的是生产异常处理入口，未削弱预期。原 QA3项 IndependentCompositionTest.kt 另按原字节进入正常回归。新的 recovery 临时突变令前台恢复保持 inactive，必须再次命中原取消断言。
