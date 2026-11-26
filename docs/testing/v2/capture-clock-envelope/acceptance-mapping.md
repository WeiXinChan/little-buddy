# 候选边界对照

这是作者对QA的14项PROPOSED断言的代码/本地证据映射，不是QA已执行或设备通过结论；QA的8个数学反模型不计入作者通过分母。

| ID | 实现/定向检查 | 未证或限制 |
| --- | --- | --- |
| M01 | README 有限E=500us/Q=0、rate与clock桥 | 绝对E/Q没有设备保证；条件性OPEN |
| M02 | ClockEnvelopeTest boundedPhase / nearBoundaryDrift | 尚在有限误差内的drift不能立即区分 |
| M03 | NativeLedgerTest累计unread/API耗时，ReadFrontierTest及CaptureBootstrapTest新frontier | 旧样本原计数不归零；不承诺中断卡住JNI |
| M04 | NativeReadLedger.sampleTime、CaptureUploads首样本age；CaptureSafetyTest新age检查 | 硬件绝对capture时刻仍受E/Q条件限制 |
| M05 | CaptureBootstrapTest固定500ms/8000/迟返/未锚定零解码上传 | 真实trace166ms条件性锚；没有另等500ms |
| M06 | raw151 replay、zeroFramePlaceholder测试，原sample0证明 | 短期可行不是物理rate证明 |
| M07 | NativeLedgerTest回退/relabeled/stale/bridge/越界，ClockEnvelopeTest新age | 未确认驱动语义的设备情形仍OPEN |
| M08 | suddenPhaseJump / accumulatingWalk / nearBoundaryDrift / allEligibleLongPair | 成熟极值永久保留；可行集合不重置 |
| M09 | ContinuousCaptureTest独立producer+有限native FIFO | 真实设备长期采样未执行 |
| M10 | OriginalCaptureTest 21/50、CaptureBootstrapTest realCapture、BootstrapSherpaTest | 受控ONNX实现回归，不是童声/模型/设备效果 |
| M11 | CaptureSafetyTest lease/cancel，CaptureBootstrapTest blockedNativeCallerClear与新frontier清零 | 真实JNI无法保证物理中断，未释放继续quarantine |
| M12 | NativeLedgerTest postAPI耗时，CaptureBootstrap deadline；原tool deadline仍在probe25 | 不得把编译或late原始成功当准入 |
| M13 | CaptureUploads首样本age→VoiceClient.input age_ms；新CaptureSafetyTest | 无CaptureFreshness类；当前实际调用链已列，不虚构端口 |
| M14 | 原FAIL/新head/Android编译证据，NativeTimestampTest runtime clockModel | 不freeze/不设备/不生产放行；匹配新版target由root统一 |
