# 图片失败提示测试客户端ACK时序

基线main08183d8caff7233bff92de7809ca2de799665281，产品源码未改，仅tests/v2/test_image_descriptions.py辅助函数/新增回归及证据。root原完整394项2错误、原模块24项1错误和只在内存改helper的实验脚本/24PASS日志逐字保留。

因果确认：run_wire在ACK原caption后先await peer.generation，但生成者最终等待session.pending清空；如果图片失败提示已入pending，生成者等测试ACK，而测试等生成者，构成自锁。慢路径也可能等到原预算失效，visual_task已经清空，导致无ACK/晚ACK测试拿到None。这可解释观测到的测试竞态，不证明产品无其它竞态。

最小修复：先进入客户端消费/ACK循环，同时观察generation与visual_task；及时ACK新提示，不等generation结束才消费。ack_help=False看见新提示即返回，保持未ACK、部分ACK/晚ACK/撤销意图。留存任务引用并显式task.result()传播异常；cleanup收集generation/visual/retired，有限观察并明确检查失败结果，不能return_exceptions吞错变PASS。没加任意等待来掩盖竞态。

3新增方法：

- 让原caption的资源退出等待失败提示音频已入队，确定性安排“提示早于主respond完成”，验证正常ACK可以完成、提示仅记已听一次。
- 同一确定性安排ack_help=False，验证提示仍pending/未记已听、generation未完成；原late/partial ACK断言不变。
- generation与visual_task的合成异常必须由helper显式抛出，不能被cleanup吞掉。

仅把旧run_wire辅助函数放回新测试，两个早提示回归均失败（old-helper-falsifier.log，exit1）；恢复修复后模块27方法0.398秒全PASS。AST比较证明原24个test方法内容/断言完全未改。

按要求复跑最终原组合：从root原项目仓库只读取得c130bfdf9c1387891104d8e079dc401049d959e6，在本任务独立detached worktree仅应用此测试文件补丁；未改变root树或生产服务。scripts/with-build-lock python3 -m unittest discover -s tests/v2 -q：397执行/397PASS/0FAIL/0ERROR/0SKIP，48.905秒，包含原394＋新增3；模块27为其子集，不重复相加。既有heavy锁/2GB上界串行执行，原套件产生temporary-preflight.json测试证据，未据此声称工作树零生成文件。组合业务源代码无本批修改；本PR不把root未合组合混入main分支。

原失败仍保留，作者0真实云/手机/部署/合并/子agent；全集包含原有本地loopback、合成HTTP/PCM/临时namespace检查，不是生产或声学验收。等待独立QA/root审合，未来最终main若有新变化须由root按需再验证，不能用此快照覆盖所有竞态。
