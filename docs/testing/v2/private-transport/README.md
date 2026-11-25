V2 私有 SSH 通道

家长管理验证PIN后，可导出本设备V2 SSH公钥；AndroidKeyStore别名为 `buddy-ssh-device-v2`，私钥不可导出。导出只产生公钥，不登记服务器、不证明远程家庭归属或V2 token授权。分享界面失焦仍触发管理撤销/关连接。

系统认证后的“导入连接配置”选择V2私有SSH，填写管理员已发行的V2专属SSH账户与V2 token。固定WSS地址为 `wss://127.0.0.1:19483/v2/voice`。设置不显示已存token或私钥；不读取V1账户/令牌。管理员须在专属账户登记设备公钥、限制PermitOpen为127.0.0.1:19483，并保留独立V2发行记录。客户端不能确认尚未连接的key已登记。

`v2.transport.V2Ssh`复用V1受审算法与JSCH依赖，独立实现/实例/Keystore别名；未修改BuddySsh或V1 Activity/配置。assets/v2-transport只含公开host、固定hostkey与CA，源自已受审V1 release-profile；已核V2 trust-anchor字节相同，V2证书SAN覆盖127.0.0.1。CA SHA256为ef47caf47e3d66b428d51a8d15c0c5960646af540c294caed37f7fcde3febe98，hostkey SHA256 base64为Z9Ty3OFZtTBeTMIS9iRfGhOIRaTJ0eRzxaMSxeggliI。构建清单对两个公开文件逐字hash白名单，其他pem/key仍拒绝。

实际调用：ParentPanelView→原系统认证/OwnerChallenge→ParentDomain加密存储连接及SSH账户→V2VoiceActivity.startVoice→V2Ssh.client→VoiceClient真实newWebSocket。WSS路径检查在请求拦截器；Socket只准127.0.0.1:19483；SSH只publickey/rsa-sha2-256、固定ECDSA hostkey、StrictHostKeyChecking=yes，TLS固定公开CA且保留默认主机验证。禁止代理、redirect、自动retry。

每次连接拥有自己的raw SSH socket、Session、OkHttp连接池；VoiceClient.close取消WSS、关闭SSH/raw socket并清连接池。HOME/失焦沿原stopVoice→releaseAudio→owner关闭路径，未完成SSH在OkHttp工作线程而不阻塞audio owner。closed实例不能重新open，旧WS回调仍按socket身份/代际拒绝。旧加密直连回环记录可读，但运行/新导入拒绝，不误判为可用或破坏PIN记录。

候选16 / 2.0.0-rc2，V2独立包com.littlebuddy.sim.v2，内部debug签名。原v15包不变；同签名向上升级保留本地记录，降级/换签名无保留保证，勿清数据绕过认证。实际SSH登记、设备Keystore和最终物理验收仍待最终测试；本批不改服务器、部署或派设备。
