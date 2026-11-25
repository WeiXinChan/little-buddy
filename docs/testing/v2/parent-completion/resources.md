首批资源/完成边界集中表。项目代码与[PR45固定资源核对](https://github.com/WeiXinChan/little-buddy/blob/be33588f905dd00ecacb0447d5bebab55e4eae17/docs/testing/v2/r88-01/resources.md)为依据；后者是519只读项目配置的事实，不冒称本作者再次读取/验证了账号额度或V2现网。没有读取/传播密钥或workspace ID。

| 项 | 当前真实路径 | 缺失值/权限/证据与后续 |
|---|---|---|
| 本机首次归属/PIN恢复 | 新增native系统CryptoObject、Keystore per-use EC签名、nonce/操作/公钥绑定、真实域最终提交 | Android11+安全锁屏与支持的系统认证；本机持有人边界不等于亲子/远程家庭归属。OPPO成功/失败/取消/系统凭据UI/HOME、密钥失效等留最终设备验收，未改手机设置 |
| 远程家庭归属/恢复D04 | 未找到真实配对issuer或恢复端点 | 具体issuer公钥/受信根、family/device claim发行端点与授权、重装/备份/吊销策略及设备token归属链。没有自动重配、安装ID或测试proof代替。本机key/record不一致隔离 |
| Android26–29 | 包可编译，系统每次设备凭据crypto路径明确拒绝不支持能力 | 这些系统若必须首次初始化/恢复，需要另外受审的已配对issuer/平台能力；不降成“已解锁/任意布尔成功” |
| V2连接配置 | 已实现系统授权后的WSS/已发行token导入与加密保存、实际VoiceClient/Capture入口 | V2公开/获准私网TLS URL与该设备专用token-file发行/作用域。现有V1 token/证书存在不能自动当V2凭据；V2默认19483无监听（519核对）。本批没有部署、生成token或复用V1 secret |
| 现有模型服务 | 519已接runtime加载现有cn-beijing/fun-asr-realtime/qwen3.8-flash/cosyvoice-v3-flash/longanyang配置；PR45 | 需root授予现有credential目录运行权限和V2监听/证书/鉴权配置。账号当日额度/供应商实际调用与效果集中最终；不新收费/云TTS采样 |
| 安全本地可听帮助 | 固定文字总可长按进入；只选系统已安装、network-required=false中文voice，并按父域上限/旧录放释放结果门控 | 具体设备系统离线中文voice/engine是否已安装与真实可听、路由、无网络包证据未知；缺失时保留文字而非云重试。包未包含伪装真人的新增录音 |
| 音量/语速/时长 | 真实加密保存、AndroidTrack native gain/rate、单调活动budget关闭transport/recorder/player | 物理音量/停声、AECTTS echo与长稳/童声验证暂停到最后。参数执行API不是声学证明 |
| 管理暂停/语音退出 | 长按后结束儿童session并显示验证，屏幕取消/退出实际可用 | M06同session暂停/水位恢复、管理独立端上有限语音取消仍待后续协议/接线，不以关闭重建声称已保留会话 |
| 自然语音管理/图像M07 | 预留带scope的management UI路由；真实反馈工厂已挂载 | backend自然管理事件及60图库prepare/reveal/hide协议由519下一批冻结。当前未装图库到APK或假揭图，不使用LLM任意文本作asset路径 |
| 反馈D02/D06 | 真实本机列表/预览/受保护操作及PR43清理执行；Provider仍Unavailable | 真实工单平台名称、endpoint/auth/维护者、所有副本/备份删除回执及期限。未伪造提交或已删除，不擅用Multica/GitHub当儿童平台 |
| 可信时间/跨重装 | 单调时钟用于本机操作、内部noBackup/AES密封 | 外部可信时间、设备凭据代际、重装恢复服务/保留执行证据仍缺，不能承诺跨设备/全副本回滚防护 |
| M14发布 | 本批沿用已有Debug签名与包/版本，附准确hash和覆盖安装说明 | 正式发行签名/版本升级、受控发布及回退流程后续批次；本批不读/生成私钥、不发布、不合PR |

本批是可审本机功能APK，不能称完整M08/M09/M07或V2全功能完成；剩余本地接线按下一独立批次继续，不因外部CI或设备暂停重做已过全集。外部资源由root集中处理，无用户过程测试/解锁/取密码待办。
