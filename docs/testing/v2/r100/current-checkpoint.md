R100 回修检查点（未完成，不作为验收通过）

生命周期回修及实际 AudioRecord 自动用例仍未完成设备验证。当前改动未发布到 PR36，不对应已交付 APK。

本地最新构建：74 tests completed, 1 failed, 2 skipped；失败用例 CommandBoundaryReplayTest 内43个实际原生模型波形回放场景中4个不符合预期：enter_polite_slow、enter_open_slow 未进入；cancel_continued_discussion、exit_continued_discussion 误执行。保留预期，不降低阈值。构建在单测失败处停止，未生成本轮匹配 APK。需要继续修完整短命令边界，完成宿主麦克风控制器及CI串行接线，再验证生产 AudioRecord→Capture→owner。

reset-probe：reset=false/true 均4次正确命中，未复现重复命中；此前只是风险猜测，不能称确认缺陷。保留原wake绝对样本映射。

原 CI6 45403092043 / e755558 为 HOME 后 native stopped/released/!recording 失败，不是第五轮返回 noUpload。M06/A01/A27/F01与R100三项均保持OPEN。当前不是OPPO证据，首装系统全屏引导恢复仍待验。没有新触发CI，没有合并或派新任务。
