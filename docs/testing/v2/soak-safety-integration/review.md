集成base：origin/main fd843b046fcd0a5033f938a6894ccc60499fbddd。
显式合入 PR116 715443314a780906565f68fd682a326339ca1057（main尚无混合驱动，修复所必需），PR117/119 0d8572a2d2cefb5c679df52d560a4aa2b7d3bd04，PR118 2f8108d0bc53aa471304d4364c40288bf1114e0d。保留各原失败与独立提交历史，不改V1/部署/供应商。PR119已有的Android仅固定帮助字面文案随依赖合入，无额外Android改动。

根因证据：original-qa.json原样保存QA来源/原报告hash/718秒终态。原turn89 half_open已收到2帧却仅ACK1；ACK1后才pause会让relay停在read等待第三包、服务端等ACK2，不再出现down blocked，.5秒观察超时。QA三个最小反例原输入/断言不变（仅导入当前源码替代QA绝对路径），保留晚pause超时反例、下一包唤醒/不转发对照。此为可复现工具竞态，非生产bug证明，亦非718秒原失败唯一根因证明。

改动只在混合驱动：PacedWire.before_ack在half_open首ACK前arm down；up保持开放让ACK1实际到服务端，等待真实down阻塞见证后才pause up，随后原时限reset。没有把pause调用当blocked、延长超时或改产品预算。新增直接调用实际PacedWire hook的正反控，验证arm不伪造blocked、正常播放不暂停。

验证：原定向集62方法PASS（含QA3反例），再新增实际hook2方法后barrier5 PASS，合计64不同方法。targeted.log与barrier.log不代表真实TLS或60分钟验收。未调用云/操作手机/部署/合并。长稳原718秒失败保持FAIL，完整A36/P14 OPEN。

执行交接：应先独立QA复核本集成，随后沿原生产server/独立driver拓扑做目标half_open+新session恢复的短原生测试，核1ACK后真实阻塞/reset/新session恢复ACK及无pending。短测通过再仅一次3600秒实时节拍长测：python3 scripts/v2_mixed_tls.py prepare --enable --duration 3600 --output <新证据目录>。该入口自身取得/继承同一heavy.lock并监督进程，禁另建锁/跳过内部身份检查；失败保留结果不自动重试。本批尚未进行原生短测或长测，不能以fixture宣称稳定性通过。
