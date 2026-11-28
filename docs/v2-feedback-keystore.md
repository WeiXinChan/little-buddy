# code41 FeedbackVault 首次持久化

code40 实机 seq39 首开编辑器 STORAGE/submitted0。确定源码路径：AndroidFeedbackRuntime 的单worker打开 FeedbackCoreOwner OS文件租约，FeedbackCore.init→load→sweep→persist→save，即使空库也会写。旧Vault给默认要求随机加密的 AndroidKeyStore AES/GCM key 强传自造IV，与该策略不兼容。noPIN管理已成功不能证明反馈库加密成功。

修复仅加密初始化：Cipher.init(ENCRYPT_MODE,key)由provider生成IV，验证12byte后保存cipher.iv；解密保持原12byte IV前缀、AES/GCM128tag、AAD little-buddy-m09-v1、ledger digest和两文件原提交顺序。无新alias/文件命名空间、无需清材料/清App数据/锁屏/PIN，既有非用户认证AES key复用；不更改设备SSH身份、私有配置或反馈授权。丢key/密文损坏仍QUARANTINED，不自动重建。

租约检查未发现需改变的行为：持有租约后才建core，core初始化失败会释放租约和channel；冲突拒绝第二writer。本次测试覆盖失败/成功重开、独占、旧格式读取重存、损坏字节保持。JVM用不可导出测试key+严格JCE provider拒绝调用方加密IV，实际运行生产Core/Vault/Owner；是Android政策的离线替身，不是AndroidKeyStore实测。最初harness发生JCE provider回退和DENIED读授权问题的日志另存，不算产品反例。修正harness后旧源码两个STORAGE反例原样保留。

Android instrumentation显式opt-in FeedbackKeystoreProbeTest#firstEmptyCoreAndExistingRecordUseRandomizedKeystoreIvWithoutScreenCredential 使用真实AndroidKeyStore随机加密/非认证key，空库Core构造及已有合成record重开；只建独立test alias和test cache子目录，finally仅清自己资源，不读/删生产反馈材料或alias。不采音/网络，不启动业务Activity。需feedbackKeystoreProbe=true；默认skip，未实际执行前不声称AndroidKeystore已PASS。不要改原native timestamp/wake专用runner白名单以运行它。

最终手机复核由root/Mac唯一任务核精确包后进行：保数据升级、直接管理、打开反馈编辑器，不提交真实用户材料；确认不再首开STORAGE及既有材料保留。不能把本修复称线上反馈上传/回执/删除链路已验。
