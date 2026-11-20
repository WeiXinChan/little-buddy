# 安卓构建、签名与 APK 交付方案

本方案覆盖 V0 互动包及后续 V1 安卓验收包，依据 [需求](../requirements.md)、[总体设计](design.md) 和 [验收方案](acceptance.md)。以下安装与构建命令是实施阶段的操作流程。

## 环境实测与实施前准备

| 项目 | 2026-11-20 构建服务器实测 |
| --- | --- |
| CPU 和内存 | 4 个逻辑 CPU，3.6 GiB RAM，约 2.5 GiB 可用，1.9 GiB swap |
| 磁盘 | 工作目录所在卷约 40 G，检查时剩余约 25 G |
| JDK 和 Android 工具 | PATH 未找到 `java`、`javac`、`sdkmanager`、`adb`、`gradle`。未设置 `JAVA_HOME`、`ANDROID_HOME`、`ANDROID_SDK_ROOT`，常见安装目录未发现 JDK 或 SDK |
| 仓库 | 基线 `c6549c5` 已含总体设计、开发计划和验收方案，当前只有需求和设计文档 |

实施时按所选 AGP 的兼容矩阵锁定 JDK、Gradle Wrapper、AGP、Kotlin/Compose、compileSdk、targetSdk 和 SDK Build Tools。按设计评审口径落实 minSdk 和 OPPO 首验矩阵。提交 Wrapper 及其发行包 SHA-256，记录实际工具版本，使用 Wrapper 构建。服务器只准备所需 JDK、SDK 命令行工具、目标平台和 Build Tools。首次安装和缓存预算 10–12 GiB，产物与运行日志约 2 GiB，保留至少 8 GiB 空闲。当前阶段只盘点和规划。

## 固定签名与备份

- 第一个正式验收包前，由用户指定签名保管人和获准的签名环境。由保管人生成专用 APK release 密钥，确认有效期覆盖维护周期，并记录别名、到期日和证书 SHA-256 指纹。V0 和 V1 在同一升级线上沿用同一 `applicationId` 和签名证书。开发调试包使用独立应用 ID 与调试密钥。
- 密钥库放在仓库外的受限位置，文件仅授权签名账户可读。密钥库和口令分开保管，口令通过批准的机密管理渠道交给签名进程，避免进入命令参数、日志、Gradle 配置、CI 缓存和产物。每次签名后清理临时副本。仓库和交付记录可保存公开证书指纹。
- 保留至少两份加密备份，放在独立的用户控制位置。首发前用其中一份恢复到隔离位置，验明证书指纹并签署一次性测试包确认可恢复。记录备份责任人、存放渠道和恢复日期，恢复后清理临时文件。
- 密钥丢失、疑似泄露或签名指纹变化时暂停发布。由保管人确认能否从可信备份恢复，或另行评审签名迁移与设备兼容性。卸载会删除应用本地数据，涉及重装须先获得用户同意。

## 版本与串行构建

- `versionName` 面向用户，建议 V0 首包为 `0.1.0`，V1 首包为 `1.0.0`。同一升级线的每个交付包分配递增且唯一的整数 `versionCode`。在发布登记中预留编号，废弃包占用的编号作废。文件名采用 `little-buddy-<versionName>-<versionCode>.apk`，登记应用 ID、Git 提交 SHA、构建配置、兼容范围及已知限制。
- 由一个构建入口串行执行。同一服务器上的 Gradle 构建、负载测试及其他重型任务使用同一个工作区外的主机锁，跨 checkout 共用。并发发起时退出并报告占用，待当前任务结束再运行。以下命令假设实施采用 `app` 模块，且 `LITTLE_BUDDY_HEAVY_LOCK` 已配置为该主机预先创建的共享锁文件绝对路径。

  ```sh
  flock -n "${LITTLE_BUDDY_HEAVY_LOCK:?请配置主机共享锁}" \
    ./gradlew --no-daemon --max-workers=2 -Dorg.gradle.jvmargs=-Xmx1g \
    :app:testReleaseUnitTest :app:lintRelease :app:assembleRelease
  ```

- 使用隔离的签名环境时，构建入口产出待签包，保管人先做 ZIP 对齐，再用 SDK Build Tools 签名。签名后不修改 APK。对最终 APK 验证签名、核对公开指纹，并读取 manifest 确认应用 ID、版本与 SDK 约束。记录此次构建的峰值内存、剩余磁盘、耗时和检查结果。不默认启动模拟器。

## 交付与 Mac 安装

1. 用 `apksigner verify --verbose --print-certs <APK>` 验证待交付文件及签名指纹。对最终字节运行 `sha256sum little-buddy-<版本>-<编号>.apk > SHA256SUMS`，并在发布说明中同时记录 APK SHA-256 和证书 SHA-256。
2. 将 APK、`SHA256SUMS` 和发布说明放在用户确认的受限下载渠道。优先使用具备访问控制且能下载此大小附件的工单；使用其他渠道时先核对权限。发布人重新下载文件并复核哈希，交付时提供下载入口、版本/提交、设备要求、安装步骤、测试结果和限制。验证下载权限时以用户账号实际可访问为准。
3. 在个人 Mac 下载 APK 和校验文件，进入对应目录，先用 `shasum -a 256 -c SHA256SUMS` 校验，并与工单记录核对。若 Mac 已装 Android SDK Build Tools，可用 `apksigner` 再核对证书指纹。
4. 从 Android 官方渠道取得 Platform Tools。在 OPPO 打开开发者选项和 USB 调试，连接数据线、解锁手机并确认这台 Mac 的调试授权。运行 `adb devices` 确认目标状态为 `device`，有多台设备时用 `adb -s <serial>` 指定目标。首次安装用 `adb install 文件名.apk`，同签名升级用 `adb install -r 文件名.apk`。安装后核对版本并试启动，确认升级保留应用数据。遇到 `unauthorized` 先检查授权提示，遇到签名冲突或版本降级先核对包、指纹及版本编号。验证结束可关闭 USB 调试。

## 真机反馈模板

```text
APK 版本 / versionCode / Git SHA / 证书 SHA-256：
OPPO 型号 / Android 与 ColorOS / 首装或升级 / 原版本：
测试时间 / 测试人 / 安静或背景声 / 距离 / 音量 / 网络：
用例编号（见 acceptance.md）/ 模拟、成人或儿童：
结果（通过、失败或未测）/ 成功次数与总次数：
复现步骤 / 预期与实际 / 错误码或脱敏事件时间 / 耗时：
影响、已知限制和待复测项：
```

V0 验证安装、升级、横屏触摸、模拟互动及停止。V1 按验收方案补语音和弱网等结果，童声云测按总体设计的数据关卡放行。反馈仅附指标和脱敏事件，OPPO 真机验收由用户完成。
