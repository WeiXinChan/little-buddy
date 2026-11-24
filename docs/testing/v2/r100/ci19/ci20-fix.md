CI19 → CI20：严格环回监听校验

CI19 run45482680223在LOOPBACK_CHECK失败，listeners=1/false，mic未启动。原artifact14963336290 SHA256 d597ca8d9e481632fa63bad8936ef68c26629076794b66e7252aa08409f17ae7。原日志未记录实际地址，不能认定与mapped IPv6复现同因。

使用ipaddress严格解析数值IP和端口，接受127/8、::1及映射到127/8的IPv4-mapped IPv6；拒绝通配、未知、非环回映射及scope。ss -ltnpH只核TCP监听，全部目标端口监听都须匹配已验证descriptor PID及所属进程树。仅记录已解析IP/端口/地址族/映射地址与PID匹配布尔值，不记录descriptor、header、token或异常消息。

本机真实临时mapped环回socket复现：ss显示[::ffff:127.0.0.1]，旧字符串规则及直接is_loopback均拒绝；新解析与所属PID校验通过。此为本机socket实验，不是实际SDK认证或CI19实际端点证据。12项脚本测试通过，包含初始化故障分支、正反地址/PID、原packet deadline及monitor清理。认证、拒匿名、Bearer、所属PID及原截止不放松。

CI20保留原完整JVM、assemble和全部设备门，仅新增scripts/m06路径触发和脚本测试。曾考虑的跨run APK复用已完全撤回；不新增artifact读取权限或固定旧制品依赖。本机不重构建Android，已有主/测试包字节不变；CI重新构建并记录其自身实际包哈希。CI19历史JVM120=118通过/2跳过及非mic设备通过保持，不冒称本轮重跑。CI20须验证实际SDK监听→认证→生产guest AudioRecord→KWS→Boundary及提示新鲜度；未执行或失败都不能称live通过。PR36 HOLD，未证项OPEN。
