本批只修后续V2应用日志的独立保留机制；A26整体仍HOLD，历史共享journal/syslog/PID1、备份/外部副本及A31 all-copies继续OPEN。PR107 TLS soak已先交付，本分支从PR106 261bc77独立起步，不混TLS工具。

已核QA log-retention-audit/review.md、counts.json：应用stdout/stderr进入默认journal并转syslog；121条可见journal正文有syslog匹配佐证（通用文本不具唯一归属），历史不足两天、当前0条超7天不证明保留策略。未导出/读取原日志正文或凭据，未安装、重启、执行真实rotate/vacuum、修改时钟或干预session79841。

新文件与边界：

- v2-journald.conf只装入/etc/systemd/journald@little-buddy-v2.conf，不能覆盖默认journald.conf。四种转发全部no；持久32M/运行8M、单文件4M/1M、文件数32/8；6day内部目标、1h轮转。journald以归档文件为单位删除，6天留一天余量，不把配置等同逐条7天物理擦除证明。
- 小时timer OnCalendar=hourly/Persistent=true补漏，root oneshot先启动专用journald实例再rotate+vacuum。读写挂载仅/var/log/journal/%m.little-buddy-v2及可选对应/run目录，不给V2动态用户systemd-journal/adm权限。
- 主服务Requires+After根清理服务，并Requires timer；稳定drop-in还追加预启动只读check。oneshot无RemainAfterExit，每次新启动事务需其成功完成，失败阻断；timer运行失败保持失败码，不假称已删除。真实systemd namespace、沙箱和启动依赖行为仍须root隔离验证，不以静态语法证明实际启动。
- helper只接受硬编码namespace，拒绝路径/通配/全局注入，子命令无shell，清空继承环境，5秒/命令上限且输出上限64K，失败只输出固定码。check仅读有效配置/路由，不读日志或做清理；sweep执行固定namespace rotate+vacuum6d/32M，随后仅取时间元数据，直接过滤<=原7天截止的记录并核最老游标。过期/坏元数据/失败均拒绝，成功也明确all_copies_deleted=false。metadata查询不落正文或cursor/boot ID。时间使用主机时钟、无修改/续期；可信时间绑定仍单列。
- v2-control核稳定安装的五文件root所有/0644/无链接/可信父目录、与受审发行逐字节一致，调用helper check，再离线业务preflight；check不创建库、不执行sweep。start/rollback选择前执行同一检查，旧包缺文件或不匹配拒绝。日志overlay/helper安装在current/releases之外，应用回滚不能移除它们；禁止通过旧unit覆盖或删除overlay来绕过。
- 发行package和verify要求五个策略文件齐备，正常hash inventory覆盖它们；部署README也包含在发行中。缺旧包不作为可启动回滚候选，root如确需退回旧业务，应先做保留新overlay的受审兼容包。

root后续步骤（本轮仅给方案，以下不在author执行）：

1. QA后从最终已合SHA打包/verify。所有源部署文件在backend/deploy/，安装文件root:root/0644、父目录root:root/0755。helper以/usr/bin/python3 -B执行，不需可执行位：
   v2-log-retention.py → /opt/little-buddy-v2/log-policy/v2-log-retention.py
   v2-journald.conf → /etc/systemd/journald@little-buddy-v2.conf
   v2-log-retention.service/timer → /etc/systemd/system/little-buddy-v2-log-retention.service/timer
   v2-log-retention.dropin.conf → /etc/systemd/system/little-buddy-v2.service.d/70-log-retention.conf
   v2-little-buddy.service → 原V2 unit位置；不改V1/default journald/rsyslog。
2. 在root选定窗口执行daemon-reload；验证有效配置没有更晚drop-in重新开启转发，systemctl show V2的LogNamespace/StandardOutput/Error/Requires/After匹配。helper check和v2-control check --apply均只读，须全过。
3. root先实际验证专用namespace可创建/读写隔离及timer/oneshot语义，再一次V2受控启动。检查失败码传播，不能把failed_closed当作删除确认。Persistent只补漏不提供关机期间物理删除保证；磁盘/namespace/时钟失效需保留过期事实，恢复后再次sweep且元数据无超期才可继续该范围判定。
4. 非内容canary分别写V2 stdout/stderr：仅专用namespace可见，默认journal/syslog不可见；V1 PID/InvocationID/路由不变。核timer有效及断档补扫、预启动失败拒绝、重启后同一条旧记录不会因新日志续期。无需用户过程操作。
5. 历史journal不支持按unit安全vacuum；syslog多服务混存不能按PID/字符串在线改写来证明全副本删除。PID1管理日志仍在默认journal/syslog，namespace不迁移旧记录。root另定共享宿主保留/隔离迁移及管理元数据范围，审计备份/快照/外部读者；本批不做全局vacuum，不修改copies=false，不声称all-copies完成。

验证：final.log为32方法32PASS/0FAIL/0SKIP（14新方法、部署8、旧preflight8、握手2）；替身journalctl只操作临时JSON归档，控制时间不改宿主机。覆盖等值7天、6天文件边界、新活动不续期、rotate必需、失败恢复、乱序旧记录过滤、格式/来源拒绝、全局路径注入、有效配置覆盖和路由、真实安装字节/权限/链接及回滚前置拒绝。旧deploy测试仅mock新增日志检查（独立新测试验证该检查），原release verify/live --check/数据库不创建断言保留。root权限元数据正例在/tmp模拟，不冒充真实安装所有权。

初始27项通过；补正例时一项因临时目录祖先元数据仍非可信而失败（targeted.log保留），已显式模拟可信根元数据、保持真实字节/权限/链接检查，最终修后通过。未减弱生产权限验证。systemd语法检查用临时unit与可用python/helper路径，未安装任何单元；namespace实际可用性仍由root验证。
