## Harness心跳生命周期修复（独立于PR93业务修复）

父SHA9fc7d4ad93f5a8b256f911748981bede53ce53a5（PR92），不复制PR93业务代码，不改生产Session/VoicePeer/lease/首响应预算。root的first-multiturn-guess-animal-4fbdd3e9.json逐字保留：三次TTS退出约151ms已confirmed、无隔离；整轮约15186ms时heard/game清空，不能再归因前轮关闭故障。

### 已核实际客户端和生产因果

app/src/main/java/com/littlebuddy/v2/VoiceClient.kt的heartbeat.run先立即send，随后handler.postDelayed(this,5000)；close移除heartbeat回调。send使用当前客户端epoch和统一sequence++。生产Session默认lease15，_live比较heartbeat_deadline/expires，过期执行clear，heartbeat只续连接lease、不续儿童闲置TTL；第一有效音频ACK后首响应预算已完成，仍须连接心跳维持后续交付。

旧harness仅bind、ACK，没有周期心跳。这次真实故障特征通过**真实单调时钟**因果对照复现：两组同一合成语音流，第一音频帧早于15s并有真实Session ACK，后续流在16.1s才结束。无周期心跳一组在结束时_session._live清掉heard/game，交付失败；正常心跳一组发4次（立即/5/10/15秒），首轮16.1s以上仍完成最终state ACK，后两轮正常。两组并行只是一个本地离线测试中的独立fixture，均无模型/供应商调用。lease=15、budget=15、ttl=600均未改，未用fakeclock；脉冲前后的expires相同证明心跳未伪装儿童互动。原件和测试日志不覆盖、不刷原实测绿。

### 最小实现

scripts/v2_multiturn_probe.py新增ProbeClient串行命令发送端口，共用本地sequence、固定该客户端epoch和Session身份；bind与heartbeat都通过实际VoicePeer.handle，不直接调用Session.heartbeat，不从服务端新epoch借权限。锁内分配seq并发送，作用域变化/关闭拒绝。client_heartbeat立即发送，sleep5后再发，无重试；失败关闭BatchState新调用门禁并取消本轮generation，标记安全布尔client_heartbeat_failed。client_heartbeats只表示已处理发送次数，不代表认证、互动或必然续租成功。

心跳Task在创建时纳入BatchState.track，原finally先关闭state/peer，再取消并用共享0.2s观察窗口回收（原隔离句柄契约不变）；没有run结束后后台心跳。补充生命周期断言确认Task.done、被state持有且门禁关闭，迟到发送拒绝且seq不增。epoch不匹配、心跳失败、并发命令seq也有针对性检查。

### 验证与交接

realtime.log：3方法PASS，实际16.138秒、对照elapsed16126ms、心跳4；lifecycle.log：新增1方法PASS。受影响harness25PASS，原独立metadata3PASS，原cleanup falsifier2PASS，共34唯一/0FAIL/0SKIP，编译/diff通过，不重跑后端全集。

无真实云/secret/config/设备/部署/合并或新agent；不改Android/PR93。实际生产TTS关闭修复仍由PR93独立QA；本PR仅修测试客户端，显式依赖PR92。合入顺序由root决定，两个独立增量可组合。后续root原监督driver可直接调用run_case，不需手工启心跳。修复不证明真实ASR/手机/语义质量/P12/P15；不自动再跑云。首轮>15s是首有效音频已按原预算提交后的长流交付，不允许首有效音频本身超预算。
