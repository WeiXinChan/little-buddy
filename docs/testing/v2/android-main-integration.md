本批从 main fd843b046fcd0a5033f938a6894ccc60499fbddd 起独立集成，只交 main-base PR，不执行远端合并。机器索引见 android-integration-index.json。

集成采用 final fix9 实际历史作为一个本地合并输入，再处理两类差异，而非按PR号逐个合并：

- PR120/121：保留PIN保存 consumed receipt 与 in-flight witness 区分、系统认证与tick/失焦/过期最终提交拒绝。保留固定枚举、256条/15分钟、独立线程、默认关闭诊断；删除旧独立RC8诊断包版本/校验模式，pinInitDiagnostics只控制诊断开关。
- PR122与123：123基于已装review快照1ae519b，不含122最终7f9544d的公钥文件释放修正。明确补回失败回调、picker失焦独立公钥流程、迟到清理/进程公共IO线程及对应测试，不覆盖123后续PIN/连接修复。公钥操作仍不在fix9普通管理流程展示。
- PR124/125：保留技术故障HOLD止环、已验证安全帮助、SSH固定目标/TLS验证和有界阶段码；一次成功不宣称WSS稳定根因已证。
- PR126–128：保留已交有限启动0.5ms/运行2ms相位模型及长期15984–16016范围、累计预算、age、时钟桥、取消/清零。2ms是有限兼容模型假设，不是Android精度保证；不因集成调整阈值。
- PR129：仅右下角长按进入家长验证；已保存连接直接复用，未保存且有私有预置时PIN→系统认证→一次确认；技术字段/公钥/发行说明不进入主流程。

main保留项：全部backend、V1代码、androidTest工具、source-snapshot独立库存校验、60图库/星星兔修正、code23/RC9普通版本和appId。资源仍固定d649ac79bc5203373ff44ebdd547bdd16772663467a22115fa75f589bef91ea1，不把旧RC8图打回main。私有模式也必须通过同一完整inventory/hash/size/PNG集合/重复ZIP拒绝，默认校验器拒绝私有产物，显式模式才可检查。

候选：2.0.0-rc9.integrated1.device1/code23，原签名与应用ID保留，可向上覆盖现code22保留记录；回退code22会受Android版本降级限制，不能承诺普通覆盖回退。无卸载/清数据操作。凭据只来自既有忽略的私有构建输入，不写源码、BuildConfig、日志或公开附件；APK本地目录0700/文件0600，仅既定私有直传路径。

验证范围：定向release门禁、PIN/owner tick/连接/公钥清理与手势/安全帮助、真实合成TLS loopback、必要Android构建、源码完整性与配对。复用fix9已验时钟/Capture/Sherpa证据并核其源文件逐字一致，不重复老全集。设备安装、实际90秒采音/长稳、童声唤醒、用户体验仍未验，今日不要求用户操作。APK资源与RC9离线backend manifest配对仅静态兼容，不表示当前已部署服务与该候选同源，也不表示已部署。

构建：scripts/with-build-lock 下，--offline --no-daemon --max-workers=1 --no-build-cache --no-configuration-cache -PpinInitDiagnostics=true -PprivateDevicePreset=true :app:assembleV2Debug。默认公共构建无私有asset/诊断。无需设备或云。
