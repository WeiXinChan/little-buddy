# V2 code40：播放写入与确认分离

基于 code39 e6e35ea。已确定的源码缺陷是 Playback 仅向 queue.first 写入，直到真实播放头到达其 end 才取下一包。后续已到包不能提前进入 AudioTrack FIFO，调度不对齐时可人为造成播放间隙。这不等于已证明用户全部电流声的根因；服务器样本无削顶和历史累计 underrun 也不能独立证明播放中断位置。

保持有界原队列（10包/24000样本）、真实 native head、暂停/取消/释放与 stall 时限。written 是跨包提交游标，head 是独立真实确认游标；单 tick 遍历至多原队列长度，partial/zero write 立即停止该次遍历，不阻塞、不补零、不重采样。已提交包保留至真实 head 逐包完成，ACK head 限于该包 end；跨多个包的 head 逐包确认，短尾未实际播放不确认。取消清零全部排队 PCM，旧 ACK 回调不能继续确认/写入后包。

未改 AndroidTrack 24kHz/mono/PCM16、minBuffer/4800byte请求、API31 240frame启动阈值、play后设置 PlaybackParams 的现有顺序、音量/语速、提示音字节、V1/native/模型、捕获及响应安全界限。现有参数可能影响真实抖动耐受，但本次不无对照调整。100ms物理缓冲不足覆盖任意272ms无数据，连续预写仅能消费已到包；不保证消除供应不足。

离线：scripts/with-build-lock python3 scripts/test-v2-playback.py。实际 production Playback+受控 TrackPort，合成递增PCM、partial/zero write、多包单tick、真实head跨包、短尾、暂停/取消/ACK内重入取消；既有Playback/LocalClarification回归。17ms泵调度、272ms到包间隔重放精确比较输出样本，并单独统计流中欠载与最后样本后的尾部空闲，不能把模拟欠载或硬件累计值换算成真实听感。

code40 私有候选沿原 signer/preset/noPIN/timeout恢复。真机应对齐同夹具、当前Track、nativehead与末帧/stop时间，分别比较流中underrun和尾部统计；不以正常ACK替代成人听感或儿童验收。原SERVER_TIMEOUT/SERVER_VOICE根因及P12仍独立OPEN。

## 两包窗口补充复核

初版三包同时注入仅证明 Playback 内部有界FIFO功能，不能代表线上发送窗口。补充用例按 backend/v2/voice.py Voice.audio 的 pending<2 准入规则，采用真实 production Playback、受控2400frame物理FIFO、每包<=2400frame、20ms完成ACK往返、17ms pump周期；8包末包17frame。此为协议窗口模型，不是实际VoicePeer/TLS或手机供数实测。

同输入旧code39与code40逐点PCM/逐包ACK一致，观测：
- 普通供数：句中缺帧336→0；末尾到固定仿真终点的空闲帧35671→36007。
- 人工272ms供数间隙：句中缺帧2784→2592；末尾空闲帧33223→33415。

末尾空闲不是吞尾音，更不能据此换算听感：完整8包与短尾均须被真实head确认，无重复PCM/ACK，只有最终样本播完才计尾空闲。272ms真实供数间隙仍产生句中缺帧，保持此负面结果，不通过补零或放宽确认伪绿。

另用4800frame受控FIFO先确实预写两包，再暂停；确认噪声恢复仅继续同FIFO不重写，真打断则清零全部PCM/flush/release，不再输出或ACK残留包。全部23项修后通过，原code39同一23项7FAIL保留（其中包含已知的预写/多包确认反例）。新增仅测试/说明，不修改code40生产代码，不重建或变更已冻结78b041e包身份。
