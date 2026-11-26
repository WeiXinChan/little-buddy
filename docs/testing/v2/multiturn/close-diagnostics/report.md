## 首次真实多轮失败的离线定位与下一次诊断

基线 de7b43819bbbaa0a059a33d50a28fd3be2b5ca15。原 first-multiturn-guess-animal-de7b4381.json 逐字保留；driver只读，不执行、不修改。并发CLI family核对仅本作者run，未用heavy/设备/云。

### 已证事实与未证推断

真实首轮4个qwen4请求成功、TTS1次/12字符、heard1项、game未提交、quarantined=true且pending0，不能判定为LLM模式错误。9939ms是首次传输音频，既无有效可听确认也未完成交付，P12不通过证明尚缺；0.04922元为未缓存价估计，非账单/P15证明。

源码因果：VoicePeer._respond在每句synthesize退出后才迭代下一句；玩法state仅挂最后一句最后一帧，由Session.ack提交。UnifiedProviders按4800字节rechunk；第一句的最终帧可已ACK并加入heard，但若此句资源退出超时则后续句/最终玩法state根本未送达。VoicePeer.resource的0.5s退出确认超时设置quarantined；Operation.valid随即false，_respond异常处理在写last_failure及发送failure帧之前直接return。因此真实报告即使加last_failure/code，仍可能null/空列表。这是当前诊断的确定盲点，不表示供应商无故障。

离线实际复用UnifiedProviders/VoicePeer.owned_resource/resource/Session.ack，两个句子和相同自动ACK，仅改变受控底层synthesize manager关闭：

- 快关闭：每句9600-byte合成上游帧实际拆成2个4800-byte交付帧，3轮均4帧/4ACK，最终game提交、资源确认可复用。
- 关闭0.65s：未改0.5s生产边界。第一句2帧/2ACK均接受，heard更新、game未提交；退出任务被取消，resource抛WireError，quarantined=true，返回时pending0但不可复用；仅调用一次TTS。last_failure=null，failure控制帧空，与上述早退机制一致。

该对照证明**慢退出足以产生同一状态组合，且模拟ACK本身在对照中正常**，不证明真实这一次必然由WebSocket关闭导致：原实测未留退出阶段/时长或实际分片计数。DashScope.speech_socket当前close_timeout=1与生产0.5确认窗口存在风险，但1是配置上界，并非实际关闭耗时证据。不得仅据配置认定根因，更不能改帧长或放宽0.5s刷绿。

### 本PR仅诊断，不改业务

scripts/v2_multiturn_probe.py 的VoicePeer诊断子类仍委托全部生产resource逻辑；透传manager的enter/exit/异常/返回值，仅记录固定枚举：resource(synthesize/planned/other)、exit_outcome、exit_ms、failure_kind白名单。没有替换生产close、延长等待或吞异常。报告增加白名单peer_failure(stage/kind)、failure控制code（未知值固定unknown）、每轮帧数/字节数与最大帧/ACK接受数/game是否提交/资源隔离状态、quality_assessable。数据仅计数、时长、固定标签；无正文、PCM、secret、URL、scope身份。metadata不能证明音频内容有效。

后续root在监督worker中原样调用现有run_case即可取得这些字段，default无observer也能诊断：若失败resource=synthesize、exit约500ms且cancelled/WireError，同时ACK已接受而final game未提交，就可直接支持关闭路径归因；若仅ACK被拒或资源已正常确认，则沿相应分支排查。资源若仍pending，保留PR90原隔离句柄/封闭计量门禁，不做重试或复用。本批不运行第二次云。

### 可审后续方案（尚未实施）

若root下一次有界单轮确认真实慢close，建议单独做**V2专用语音adapter**：在其0.5s资源确认预算内分配更短的正常协议关闭时间，必要时由底层传输可验证的中止/关闭机制收尾，并等待确认socket/任务实际不可再用；不能将后台close假报成功，无法确认仍隔离。具体传输API和关闭证明须按锁定websockets实现核验后另审，不能假定cancel就是释放。V1通用DashScope/生产resource的0.5s边界保持，亦不修改帧长。当前PR无该业务修复，不宣称生产问题已消除。

### 检查

原13＋清理6＋新增诊断3＝22PASS，原QA清理falsifier2另列2PASS，共24唯一方法/0FAIL/0SKIP。只跑受影响harness集合，不跑后端全集。编译/diff通过。原首次云失败与旧清理失败不覆盖；新metadata/日志在同目录。新3项分别检查快关最终提交、慢关因果及secret样式未知值的白名单过滤。合成9600-byte帧不是本次真实供应商分片证据；下一次真实分片只记录数字。


## D92-01：本轮提交证据更正

旧f76c1c3b的game_committed=bool(game)确有跨轮误报，独立QA原27执行26PASS/1FAIL保留，不能沿用旧字段证明失败轮提交。commit-evidence目录保存逐字原metadata_checks.py与失败日志，原输入和断言未改，修后原3方法通过。

现game_committed仅表示**本轮Sink观察到真实公共玩法state的最终ACK提交分支**：本轮每次audio回调，先读实际pending队首候选项；真实Session.ack返回True后，确认该候选与音频segment对应、带state且非private、达到candidate.end、turn保持不变、候选已从pending移除、topic恰加1，才增加本轮观察计数。同步读后观察，无复制ACK/提交逻辑、无写Session，也不根据game新旧值推测。每轮计数重置；旧game存在不作为证据。True表示观察到该分支，False表示未观察到此轮公共state提交，不表示旧game为空；此为合成ACK下的生产状态提交证据，不是实机已听证明。

原跨轮反例第一轮提交旧规则，第二轮新规则在首句slowclose失败时，字段现为False；同值state连续重提3轮仍均True并且topic各推进1。新增边界还验证不同值提议无ACK后取消不继承旧计数、私事state即使ACK接受也不计公共game提交。原resource委托/0.5s确认/取消异常透传/计数隐私检查保持。25受影响＋原QA metadata3＋原清理falsifier2＝30唯一方法全部通过、0skip；不扩大成真实玩法或P12/P15通过。首次真实失败原件和前轮证据保持不变。
