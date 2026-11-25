本轮仅host-only只读native诊断，冻结交root live review。未放行冻结树前禁止push/CI28，不重跑48c1，不建Android/phone/云调用，不改生产source7、SDK/格式/音量/阈值/TTL/HAL，不tinycap/setprop/nativehook，不另加音源。

事实与目标

CI27 run45520060347/job138889361611，artifact14978984895，SHA01a4f475c1cc38d04c2367845d0b1b4075b5499a0866156319df2e02e4fc9200：source7/session97 READ、实际PA隔离、一次true/一次paplay/零inject、host原64960正文corr.989176916和owned回收后false通过；guest126080样本峰8/首秒后零、源同版hit/guest无hit，live kt154 FAIL。九组16项通过，JVM/新鲜度零上传后续NOT_RUN。不能再归PA没播/SDK一直false，gRPC覆盖不是唯一解释。既有PA控制及原fixture/600ms零前300ms尾/8秒128000不变。

执行顺序

- workflow显式export ANDROID_SERIAL=emulator-5554，父pa_only_calibration在run_arm之前完成身份/PrivatePulse完整owned QEMU/私有两null门。需M06_NATIVE_READONLY=1、SDK/synthetic既有门、API36 fingerprint精确匹配、非已知stub。
- 仅一次 adb -s emulator-5554 root（4096字节/8秒）；成功才wait-for-device（4096/8秒），id -u（128/2秒）须实际0。拒绝/异常/截断UNAVAILABLE，无第二次root、不找用户。准备失败不伪称native通过；原已审PA和所有mic/九门仍保留，只有原门才决定其真实结果。
- 受控pipefail下ps -A -o PID,UID,NAME由guest awk只投影NAME精确等于android.hardware.audio.service的PID/UID/NAME（16KiB/1秒），再选唯一进程；实际UID与/proc stat starttime、status Uid、/proc/PID/exe校验。exe仅/vendor/bin/hw/android.hardware.audio.service。PID/UID/starttime换代拒绝该次归属，不追新PID。后续观察只resume已核receipt/id0，不重root。
- 播放前取实际HAL白名单映射及对象SHA/BuildID；PA原paplay启动后只置event/记录单调时钟，不阻塞或延播放。原metadata owned线程做只读snapshot，最后join仍在SDK false之前。SDK/PA/native各自时间不混为同一时钟。

精确查询白名单与输出界限

| 对象 | 命令/范围 | 输出与界限 |
|---|---|---|
| HAL identity | 固定PID下awk取/proc/PID/stat的PID/starttime；status只取Uid；readlink exe | 2048字节/1秒，PID动态值必须是已核正整数，无cmdline/env/mem |
| maps | awk在guest内仅投影末列匹配的/vendor/lib或lib64下路径 | 8192字节/1秒；去重最多8对象，不传全maps/地址 |
| 实现对象 | hw/android.hardware.audio@7.0或7.1-impl(.ranchu).so；精确hw/android.hardware.audio.legacy@7.1-impl.ranchu.so；hw/audio.primary.ranchu.so；libtinyalsa.so | 未知路径拒绝，不扩大任意lib扫描；空/权限失败UNAVAILABLE |
| SHA | sha256sum 已核路径 | 1024字节/1秒，仅64hex且路径一致，文件SHA不声称内存逐字hash |
| BuildID | 仅已有/system/bin/readelf或/vendor/bin/readelf -n 已核路径，awk仅Build ID | 2048字节/1秒，pipefail；无工具/权限/未知ID则UNAVAILABLE，不安装/下载guest工具 |
| ALSA | 固定/proc/asound/cards、pcm、card*/pcm*c/sub*/hw_params/status | 16KiB/1秒，仅ALSA_PATH、card/pcm编号及rate/state/owner_pid/period/buffer/hw_ptr/appl_ptr等既有白名单；不可读不等于无设备 |
| snd | ls -ln /dev/snd | 16KiB/1秒，仅char节点mode/UID/GID/major/minor和固定control/pcm/hw/timer/seq名 |
| driver | /sys/class/sound/card*/device/driver的readlink -f | 16KiB/1秒，仅card号和/sys/bus/pci/platform/virtio/drivers受限路径 |
| mixer | command -v tinymix，只有/system/bin/tinymix或/vendor/bin/tinymix才无参数读取 | 16KiB/1秒，仅Capture/Mic/Input受限名称、INT/BOOL/ENUM；单TAB或至少两个空格列分隔均支持；BOOL On On为bool数组，未知值不输出正文；不写控件 |
| logs | set -o pipefail; logcat -d -v epoch --pid=已核PID -T guest秒.000 android.hardware.audio@7.1-impl.ranchu:V '*:S'，guest awk投影 | 8192字节/1秒，最多回看20秒且不早于本轮准备；仅PCM_OPEN_NULL/FAILED、PCM_PREPARE_FAILED、PCM_READ_FAILED、FALLBACK_TONE、LATE_SILENCE及计数/数字/错误码，不传任意body/全logcat；producer失败/截断不可记AVAILABLE零错误 |

单次snapshot有8秒发查询预算，截止不再发查询；既有bounded子进程TERM等待1秒、必要KILL等待1秒单独有界回收，不扩大播放/guest采样或任何产品等待。AVAILABLE表示根身份/该项采集成立，各子项独立状态；可选工具缺失不会抹去已取得ALSA/对象数据。PID/对象归属变化则该次快照UNAVAILABLE。

时间与会话边界

snapshot、对象指纹和关键section都有实际host monotonic起止。paplay进程start/end由原helper非阻塞callback密封，重复finish不续窗；不当成精确声学起止。回收后每section和Flinger查询分别标FULL/PARTIAL/NONE/UNKNOWN重叠；请求phase只是PA_REQUEST_OBSERVATION，晚读完的section不能称播放中证明。日志有guest epoch窗口，但读取重叠不代表每条历史事件都发生在PA窗口内。

source_evidence明确只是fixture request时held Capture/RecorderProof快照；与本nonce active Flinger的live输入track/session及mic-pa-nonce.json实际QEMU归属分别关联。Flinger只保live输入handle/rate/format/source/track IDs/effect count和明确gain/mute值，未知不套默认；忽略Historical Thread Log。只有可解析live track且active严格True、匹配request native_session才记匹配，没有匹配UNAVAILABLE，不混入后续恢复session。

证据边界与回归

本机不执行adb root、不启动AVD/音源。完整NativeReadOnly.prepare/resume/snapshot由受控FakeADB回归，且实际宿主awk过滤/pipefail用合成元数据跑过；不把模拟身份/文件SHA/BuildID当GHA实际native证明。覆盖父serial真实init顺序、单次root/id0、拒绝不重试、legacy路径、PID中途换代、对象缺失/集合变化、权限/超时/截断/UTF8、未知字段/枚举、bool双声道、producer失败及时间窗口/恢复session负控。root放行后才新CI28一次，复用b2原APK和已审PA-only、原mic+九门/cleanup，enter过后继续原提示/新鲜度/零上传矩阵。

参考android16-release编译tag来自官方Android.bp，但未匹配本轮实际ELF BuildID；reference defaults/late-silence/fallback不当实测。无tag事件也不证明无故障或debug日志已启用。只有实际objects/PID/计数原件能收窄候选，不承诺本次可定唯一根因。

后续待办，未混入本补丁

global90 head48c1/run45520060339 API36 job138889361730真实FAIL：36/36设备、SSH、JVM TLS1过，但wake-flow connections2/ready2/first_pcm2/sealed1/exact1（要求2/2）。不能称infra；客户端ASR_UPLOAD_END入队不等于服务端收到END是源码正控时序候选，尚无哪turn/取消或日志晚到的原件定因。以后必要Android测试构建/恢复常规workflow时，仅test-only按每turn已有服务端完成信号因果等待后Stop，保2exact门及V1取消产品行为，配可控暂停反例。本轮不改app/backend、不重构/重跑global90；API26已实核SUCCESS（job138889361437），API36独立wake-flow完整性FAIL仍保留，不能因26成功把global90整体称通过。PR36 HOLD、未证OPEN。
