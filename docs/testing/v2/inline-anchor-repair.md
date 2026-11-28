## 第二轮证据，与首轮分开

0d42f0f已由root确认相同Qwen入口的第一轮game/rules/played context/audio通过并上线；不回退/重写该冻结版。本补丁是独立后续分支。

root报告 `guess-delivery-0d42f0fe1a017525a1a385a11b6682167c7a6fe0.log`：同一case SHA d4dd8bfb352a5ecb75c2eabe197a9c7adc1bc66c09eaee22444ff8eb43d4b2c5，总7次文本；第一轮两个PLAN+FACTS+审核、42次模拟ACK且game commit；第二轮两个PLAN+FACTS，最终ModelError/plan_anchors/anchor_index_range，零第二轮音频/ACK。不能把它再归为第一轮QualityFault，也不能说没进入PLAN再生成。日志未保留两次具体索引/句数，不能断言是1-based或跨历史索引；首个错误细类也不能从最终错误倒推。

现有修正仍让模型返回同样的数值索引；schema只限制0..3，无法表达与本轮len(sentences)的关系。虽然提示说从0开始且小于实际句数、本地验证正确拒绝越界，重新请求依然可能重复错误。因此不是放宽本地边界，而是降低修正输出的表达难度。

## 只改变已有format repair响应，不增加调用

正常首个PLAN的schema/提示/输出结构完全不变。仅原白名单anchor_index_type/range已获准的那一次完整PLAN重生成使用PLAN_FORMAT_REPAIR：

```json
{"action":"continue","mode":"guess","guess_role":"setter","rules":"每次一条线索","roles":["瓦力出题","孩子猜"],"secrets":{"answer":"兔子"},"sentences":[{"text":"它有长长的耳朵。","anchors":["clue.current"]}],"tools":[]}
```

该DTO禁止顶层anchors与数字索引；每个标签直接附在模型选择的真实句子对象上。严格验证完整DTO后，按数组位置编译原运行时sentences/anchors，原全部PLAN本地语义/句数/角色/secret/tool校验继续执行。不是修改已拒草稿：不传回旧草稿，不把字符串/布尔索引转数字，不clamp到0，不截句或静默弃标签。重复标签、未知字段、数字标签、旧格式响应等都失败关闭；现存谜底不能因修正而被偷换。

所有接受的标签索引由实际数组位置生成，所以不存在合法inline DTO编译后anchor_index_range越界。旧完整文本/标签都保留，semantic tag仍由模型明确附着，整体及分段审核、真实ACK后state/facts提交规则不变。若模型不遵守新DTO仍失败，不做第三次调用。仍共用原一次read retry和原15s，不额外PLAN/FACTS/review请求，不替换模型或收费回退。private、预算已用、旧输出已有效播放/pending、非白名单错误等原限制不变。

probe新增可选plan_format_repair={initial_detail,encoding,validated}：initial_detail仅原index_type/range，encoding固定sentence_labels，validated是严格bool；只表示完整PLAN经校验，不代表安全审核或播放通过。无草稿/标签正文/秘密/用户文本。无修正为null，不作为0或失败。多turn开头清零，避免旧回执混入新轮。新增固定anchor_inline_duplicate诊断枚举，独立reader需同步白名单，不能放开任意字符串。

## 离线验证与真实验收边界

- 实际Qwen HTTP adapter及Canonical Schema：正常首个PLAN仍原schema；format请求才使用inline对象/控制标签。
- 不丢任何句子和标签，1..4句的编译索引都严格在当前范围；数字标签、旧索引响应、重复/未知字段不被归一化，其他完整PLAN约束仍生效。
- 既有预算/取消/revision/原谜底/网络与格式共享槽/二次非法终止/ACK后commit回归保留。
- 实际VoicePeer/模拟ACK三轮固定case：第一轮正常，第二轮首个PLAN故意1句index=1后用inline重新生成，第三轮交换为guesser；三轮交付/当前谜底/角色及cleanup确认，第一轮无format修正。该受控模型只证明代码和协议，不证明真实Qwen会始终遵守。

```sh
scripts/with-build-lock python3 -B -m unittest tests.v2.test_inline_anchor_repair tests.v2.test_plan_format_repair tests.v2.test_visible_model_contracts tests.v2.test_omni_text
```

root仍应以相同固定case/当前Qwen配置和原预算入口验证后续轮，记录新回执与实际usage/delivery，不因一次正常未触发修正的成功就声称覆盖修正分支。不动已上线0d42，待root评审/CI/复测后再决定激活新source；作者不做手机/供应商调用/部署。APK、wire、ASR/TTS与pending_guess首轮质量修复不变。
