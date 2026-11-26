PR87 site-local IPv6最小修复

原head76be1a7fb789aef8d2cd16d3be955c4d202dab89：QA发现、root独立复现fec0::1被public_addresses放行。原root JSON原样保留为root-original-failure.json，作者在修改前再次零网络复现并保留author-original-reproduction.json。不能用原99方法PASS覆盖此真实遗漏。

生产只在image_download.public_addresses的原组合谓词中加IPv6 is_site_local检查；Python对此地址is_global=True不能单独说明公网。其他is_global/multicast/reserved/unspecified/loopback/link_local/IPv4-mapped/6to4/Teredo、family/port/zone以及混合记录整体失败规则全部保留。免费路由/模型/审核/lease/字面连接/TLS均未改。

新增4方法：fec0::/10首地址、末地址及中间样本均在任何connect之前拒绝；下邻febf:ffff...按既有link-local、上邻ff00::按既有multicast拒绝；公网IPv4/IPv6与site-local任意次序混合均整体拒绝；正常2606:4700:4700::1111及2001:4860:4860::8888仍以字面IP连接443、TLS使用原供应商host并关闭stream。再核22个原特殊地址样本覆盖IPv4私网/CGNAT/本地/链路本地/文档网段/多播和IPv6 ULA/链路本地/文档/映射/6to4/Teredo等。都是合成resolver/stream，没有真实DNS、TLS或云调用。

fixed-regressions.log：103执行/103通过/0失败/错误/跳过，分解为原18新增边界＋本次4新增＋原图片相关81（含4个原负控检测）。正常99方法＋4个原负控方法，不能与前次99总方法混同。fixed-address-results.json列零网络实际判定。原18/81旧日志仍保留历史位置，没有伪造替换其coverage。

修复后固定head/tree交既有QA run01a21630-7291-79c0-8c52-871bd135cf74增量复核；PR仍等待root审合，真实单图暂停保持。本批不forcepush/合并/部署/改secret/config或设备，qwen4-max和免费quota路由不动。其他QA发现继续同PR收敛。
