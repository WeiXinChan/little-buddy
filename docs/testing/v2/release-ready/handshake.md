## Android发行契约最小接续

显式依赖PR53固定421e074b051c7e49d9ccca3f5bd48578976fa020，不覆盖PR53或其已交来源包快照。b30交付准备需要从正常认证控制帧确认版本，然后才启动儿童capture，本补丁仅改后端/发行清单与最小反例，不改Android。

正常scope增加`protocol_contract:"v2-voice2-safety1-images2-volume1-management1-end1"`，原epoch/session/turn/revision/management_v=1/state不变。单一backend.v2.protocol常量供运行握手和preflight/manifest共用。该字段只说明版本，不赋家长权限、不携token/环境/正文、不从failure建立能力。Android当前连接先scope，当前scope/management_v/契约精确匹配才开本地capture，缺字段/未知/不匹配拒绝；实际客户端断言归b30独立树。

发行release-manifest.json维持format=1/source_sha/protocol_contract/files，增加显式`assets_manifest_sha256`，精确匹配`assets/v2-default/manifest.json`的inventory hash及真实内容；verify拒绝缺失、格式错误或不一致。旧PR53包没有这个显式字段，不冒称满足新静态兼容器；root组合新APK时应使用本补丁固定包。版本/60图hash不是身份或TLS信任证明。

最小4方法通过（新正常1＋错误scope契约负控1，原发行完整性与真实CLI loopback抽查2）；包括真实TLS正常scope字段和READY/SIGTERM，资源hash漂移拒绝。Python编译/diff通过，无新供应商调用、部署或设备。不复跑13或大集合。最终新包实际head、format、协议、素材SHA、包SHA在交付附件及评论，PR53快照保留。
