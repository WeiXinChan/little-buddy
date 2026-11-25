本轮交可覆盖安装的集成APK，M14正式发布尚未执行，不把Debug产物称正式版。

- 当前包 `com.littlebuddy.sim.v2`，versionCode13、基线名 `0.1.12-animal-private-v2-m04`；以固定SHA/tree/APK哈希识别本批，旧版本名不作为能力证明。入口是V2VoiceActivity，V1包/服务不改。
- 延用既有Debug证书SHA256 `7705f543347ae9ec1de4ae4b0dc24f73b0a472fb32ecc06cca0d112a8fe75e10`；不读/复制私钥，不生成替代密钥。正式发行需root确认受控签名、版本登记与发布渠道，暂不公开分发。
- 安装说明仅用于后续授权验收：`adb install -r little-buddy-v2-management.apk`。本轮未安装；签名冲突或数据schema不兼容时停止，不擅自卸载/清数据/降安全属性。
- 配置导入继续要求PIN后新的系统签名：wss固定/v2/voice、无userinfo/query/fragment、已发行32–256 alnum设备token。receipt不是连接token，V1 token也不自动升级为V2身份。真实URL/证书发行/凭据作用域由root集中提供，不写在附件/日志或Intent。
- 本地record schema2/AES密封与PR46一致。回退优先同证书、兼容schema2的固定旧产物；不能把早期仅schema1读取的APK、清数据或重建缺失密钥当回退方案。固定前后包哈希、证书、版本及已有记录兼容证据，最终集中验证覆盖安装和失败回退。
- 最终集中门槛含系统认证取消/失败/登记变化、管理零儿童PCM/本地KWS误触与释放、receipt跨页/跨连接/过期/换人、图片ACK/迟到、正常结束、安全帮助、离线voice、音量时长实际执行、后台/HOME/长稳及设备声学。此清单是未执行项，不是PASS或用户过程待办。
