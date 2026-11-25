B metadata-only 最小冻结方案，待 root 审定。本轮未 push/CI/AVD/adb/root/新音源，不影响正在运行的 CI32。PR36 HOLD，fixture 未证 OPEN。

范围为 `enumeration_metadata.py`、NativeReadOnly 的显式 `enumeration_metadata()` API 和纯解析/模拟 runner 负控；没有改 workflow、HDA runtime_gate、PA 或生产代码，没有执行此 API 的设备入口。基线为已发布 CI32 同树本地1a9f5cd，远端f6f63ac / tree66feeb6e2cf686fbec8622d49b6836d267a50727。

## 执行设计与权限分离

只有后续另获执行授权的 metadata-only caller 才调用此 API。复用原 owned synthetic 私有隔离、单次有界 root/id0 的 prepare 成果；本 API 自己绝不调用 root/prepare/重连。未 rooted/HAL 不成立立即返回 UNAVAILABLE。默认 MetadataPulseView(self.proof or PrivatePulse()).verify；也可显式传入 metadata_proof。严格校验返回 dict 的 proof_scope=BASE_METADATA_ONLY 后，再走原 PID/UID/starttime/exe guard 和 mapped object 集合一致后才采集；结尾再核 PID 与 object。不新建降级身份，不把本机 mock 当 GHA。

本 API 先建立固定8秒单调 deadline，所有查询和前后 guard 共享，不为文件/重试续期。每条 read 最多 min(1s,剩余预算)，总预算到期的未读项明确 COMMAND_FAILED/TOTAL_BUDGET，不冒充 EMPTY；已有 typed 事实保留，结束复核失败则 identity_rechecked=false/UNAVAILABLE。沿用 bounded 的 owned 进程超时 terminate/kill/join；清理不构成新读取预算，实际时间戳保留。没有新增外层重试。

输出始终 mode=METADATA_ONLY、fixture_authorization=false。没有 HOST_AND_GUEST_HDA 授权、没有 arm/SDK/音源调用。旧 HDA 正向 guest 门未知仍 STOP，不接此输出作肯定证据。正常 workflow 此次完全未改。

## 固定命令与 caps

完整命令常量在附件 patch 的 `enumeration_metadata.py`，不依赖用户输入路径。

| 对象 | 查询/允许输出 | 单次上限 |
|---|---|---|
| 内核 | `uname -r`；固定只读 `/proc/version`，只提取合法数字开头 release token，丢弃 builder/任意正文 | 各2KiB/≤1s |
| ALSA基础 | 固定 `/proc/asound/cards`、`/proc/asound/pcm`，`[ -r ] || exit 44; cat` | 各4KiB/≤1s |
| capture清单 | 固定 card0–7、pcm0–31 capture、sub0–7 的 hw_params/status 路径；无匹配为 EMPTY，最多32个文件，重复/超限/未知路径拒绝 | 清单4KiB/≤1s；每文件2KiB/≤1s |
| PCI | 只遍历 `/sys/bus/pci/devices/*/class`；仅 class0x0403xx 继续固定 vendor/device、driver readlink；合法BDF，总BDF最多64个（非audio也计数，第65项在读取class前exit46），16个audio设备上限；只存数值ID与受限 driver 路径 | 8KiB/≤1s |
| card关联 | 固定 `/sys/class/sound/card0–7/device` readlink，保合法 card→PCI BDF；未知路径不导出 | 4KiB/≤1s |
| 驱动存在性 | 固定 `test -d /sys/module/snd_hda_intel`，只 PRESENT/ABSENT | 128B/≤1s |

优先取得 ALSA基础、路径清单及内核/PCI/关联/模块存在性，再读可选capture详情，避免子流数量耗尽预算而无PCI事实。整个观测共享8秒，不是逐项8秒。最多32个capture文件，原始读返回总cap小于100KiB；只保存typed投影，不落原始正文/任意异常消息。PCI子命令cat/readlink失败以非零45保留COMMAND_FAILED，不能误称无设备。

ALSA逐文件 state 严格为 NO_SOUNDCARDS / EMPTY / PARSED / UNREADABLE / COMMAND_FAILED / TRUNCATED / UNRECOGNISED。明确无声卡只接受cards完整标准标记；PCM空白只EMPTY；permission/missing exit44为UNREADABLE；非零/未EOF/超时为COMMAND_FAILED；cap或超限为TRUNCATED；未知行不猜、无原文。卡只存索引/id/driver enum形状，PCM存card/pcm/capture/playback，capture只存有限数值与状态/format/access白名单。未知卡/driver或路径语法不外推硬件类型。

版本/PCI/声卡关联可区分“已枚举audio PCI但driver NONE”“driver关联存在但没有已解析card/PCM”“所有这些仍未知”。snd_hda_intel目录ABSENT不证明CONFIG=n，EMPTY音频PCI不证明SDK未创建设备；必须结合完整状态、时间与身份复核。只投影现有直接PCI card链接，桥接/其他路径为UNRECOGNISED，不按非HDA推断。

## 禁止面

无proc/config.gz解压、模块文件扫描、完整maps/logcat/env/config/resource/rom、内存/PCM；无模块加载、bind/unbind、setprop、effects/增益、镜像SDK/格式/阈值/TTL变更。没有新增fixture或设备输入。参考源码不冒充实际二进制行为。

## 纯解析负控与边界

完整host suite 99 PASS（原91+新增8）；包含标准HDA卡/PCM/status、NO_SOUNDCARDS/EMPTY、未知和非法路径/BDF/driver、重复PCI、kernel正文丢弃、权限/命令/EOF/超时/截断/非法UTF8、8秒耗尽、mock完整流水线、未root不发命令、PID变化不采集、末次对象变化保事实但撤关联。shell仅执行bash -n语法检查，未执行查询。

首轮完整发现新测试缺sys.path绑定导致ImportError（91执行+1导入错误），已保存原日志并修正隔离导入；最后99全部PASS。曾有单个mock查询计数断言10/实际9的测试编写错误，改为按实际固定查询9核验，不是设备或产品缺陷。没有Android/JVM/TLS重跑，本轮实际native观测全部NOT_RUN。

交root核完整命令/输出caps/安全顺序后，再结合CI32终态决定是否执行B；本冻结不能当执行授权、HDA支持证明或产品验收。


## root 初审后的接线修正（取代初版默认 FULL 调用）

显式 API 为 `enumeration_metadata(metadata_proof=None)`。默认使用 MetadataPulseView 包装底层 PrivatePulse，绝不调用 FULL verify；显式 proof 也必须返回结构化 BASE_METADATA_ONLY。错误scope/基础隔离失败在任何native guard/query之前停止；此view只留在本方法局部，既不赋值 self.proof，也不传PA。原真实PrivatePulse.verify_metadata_only保留owned UID/exe/祖先、私有socket/-n、两null拓扑及QEMU后端环境全检查，只省略最终host HDA肯定证明。原HDA fixture门完全未改。

新增负控实际执行默认NativeReadOnly→MetadataPulseView→PrivatePulse._verify(True)完整Python接线（OS/proc/Pulse传感器由固定模拟数据替代，不运行服务/设备），M06_REQUIRE_HDA=1下FULL对缺soundhw/feature的同一实例抛HdaStop，而BASE完整隔离成立后可采集；owner改变后BASE拒绝，guard/collect/native runner均未调用。scope空/错误/None均拒绝。模拟身份不代表GHA实际证明。

PCI循环总目录数计数硬上限64，超过时exit46→COMMAND_FAILED/PCI_BDF_LIMIT，丢弃部分输出。纯本地临时伪sysfs树64/65项反例执行固定shell循环（仅替换固定sysfs根为测试目录），没有实际/sys/adb读取；证明输出条数不是枚举上限。其余1秒/8秒预算和caps不变。

此前默认FULL接线是root审查指出的源码风险，本轮未在设备复现；本地mock传感器漏分支曾导致测试失败，补齐后通过，不当设备事实。CI32终态及匹配包由root/协调实核：JVM/assemble、九组16门通过，live仍FAIL、新鲜度NOT_RUN；本轮不查询/重跑CI或外推验收。

最终冻结回归：CI关键环境 M06_REQUIRE_HDA 未设/0/1 三组各102 PASS（原99+本轮3），日志分别保存。未执行任何设备/服务命令。
