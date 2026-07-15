# dongkl 批 ask 题面/选项检查(2026-07-15,只记录分析,未改代码)

> 用户要求:跑 dongkl 脑图,重点检查 ask 的内容和选项,遇到问题只记录分析。
> dongkl = "CNAME pool 支持 ipo 算法"批,34 案,算法类(rr/wrr/ga)+ CNAME pool。

## 发现 1(好——验证设计正确):算法类欠定题面优秀

593484/593545(absolute_position/weight_ratio = wrr 位置/权重分布)走 generic 数学
模板,题面质量高:
- 593545:"wrr 轮转起点由运行时计数器决定,不保证从第一个 pool 起;wrr 权重 [3,2,1]
  需至少 Σ=6 次请求才能体现比例,实际仅 3 次。最小可验请求数 6 次。"——数学判词精确、
  可验性说清、给最小请求数;选项(改过程加请求≥6 保留顺序 form=member / 改预期改关系
  形态放弃顺序 / 改描述挂起)清晰。
- **验证审计"算法分布类不套三元组、保留 generic 数学模板"是对的**——三元组(test_point+
  obstacle+equivalent)对"轮转起点运行时不可验"这类数学欠定会失真,数学判词更贴切。

## 发现 2(真问题):command_existence 门语义盲区——worker 产出的错误命令被当"版本缺失"

门无法区分两类"命令不在手册":
- **(a) 脑图意图要求的功能命令在此版本不存在**(yzg 668059 `sdns fulldns on`——脑图
  明确要 fulldns)→ 合法欠定,呈报用户 ✓;
- **(b) worker 产出的错误命令**(编写 bug)→ 该 reflow 重写,不该当版本问题呈报。

dongkl 三案全是 (b),脑图对照证实:

| 案 | 脑图意图 | 门抓命令 | 真相 |
|---|---|---|---|
| 681811 | 修改 pool 成员,ga 算法测试 | `s` | worker 残缺命令(单字符,脑图无此命令) |
| 778012 | 新增 pool,rr 算法测试 | `sdns clear all` | worker 词序错(正确 `clear sdns all`) |
| 778041 | 修改 pool 成员,rr 算法测试 | `clear statistics sdns` | worker 命令不全/错 |

**后果**:
- **题面误导**:681811"用例用到的命令 『s』 查不到"——用户看 `s` 困惑(脑图是 ga 算法),
  掩盖 worker 产出残缺命令的真问题;778012"『sdns clear all』查不到"诱导用户以为版本
  缺失,实际是词序写反。
- **选项全错**:command_existence 选项 3"挂起待适用版本;文档不一致如实写报告"——但这
  不是版本/文档问题,是 worker 编写错,正确处置是**重写正确命令**(reflow),非挂起待版本。
- **`s` 单字符**尤其刺眼:门未过滤明显残缺命令(长度过短/非合法命令形态),把 worker
  垃圾产出当"版本缺失"呈报。

**根因假设**(待验证,未改代码):`_gate_command_existence` 扫卷面命令 vs 手册签名,抓
"不在签名集的命令"→ 欠定呈报。它缺一层判断:这个"不在手册"的命令是**脑图溯源的功能
命令**(→合法欠定)还是 **worker 自造的错误命令**(→编写 bug,reflow)。区分信号可能有:
①命令形态残缺(单字符/非命令结构)→ 明显 worker bug;②命令词是否溯源脑图 step
(脑图无此命令词根 → worker 自造);③相近命令存在(clear sdns all 存在但 sdns clear
all 不存在 → 词序错,非功能缺失)。

**注意与设计红线的张力**:门不应硬编"正确命令词序"(那是领域知识,归 worker 查手册)。
但"命令形态残缺(单字符)"和"脑图无此命令词根"是**结构化信号**(非领域知识),可用于
区分 (a)/(b)。修法方向留待讨论,本轮只记录。

## 观察进行中

上机 verdict + 其他 ask(s₀/bed/更多欠定)待检查,完整后补充。

## 发现 3(好):14 fail 归因健康,无 s₀ bed 假阳

层分布:V 9 / E 3 / G 1。唯一 h_s0(593573)disp=reflow → 不进 bed(disp 不匹配
rerun_isolated/transient),走 V 层 reflow 重编(现象=dig 4次全返 p1 成员,算法分布
问题)。**dongkl 这批零 s₀ bed 假阳呈报**——§18.14 效果验证(fail 走深归因)。
- defect_candidate(572741 clear sdns host method 无效果、105941 CNAME lastresort)+
  expectation_suspect(572708)正确归类为产品缺陷候选。

## 发现 4(印证发现 2):command_existence 与上机 fail 对同一 worker bug 矛盾处置

778012/778041 既被 command_existence 门标欠定(错误命令 sdns clear all/clear
statistics sdns),又上机 fail 走 V/G reflow("未向 .70 发 SDNS 配置命令"/ipv6 命令
问题)。**同一 worker 编写错误,两条路径给矛盾处置**:门→欠定呈报(挂起待版本),上机
→reflow 重写。正确的是 reflow(重写命令),门的欠定呈报是误导。进一步坐实发现 2:
command_existence 门该区分脑图功能命令缺失 vs worker 自造错误命令。

## 发现 5(新,待确认):DNS 单标签超长 lint 盲区

994838(155字符)/994869(128字符)单标签域名 > DNS RFC 63 限制,被 dig IDNA2008 校验
拒绝→上机 fail。`structural_gate._check_dns_label_limit`(≤63)本该 emit 期拦截,但
这两案上机 fail 说明 lint 未拦或被绕过(可能:域名在 I 注入/RUNTIME 回填、或标签边界
识别盲区)。待确认 lint 为何没抓(只记录,未查根因)。

## 发现 6(好):expectation_suspect F1 面板质量优秀(dongkl 首次真实触发)

572708(no sdns host method 命令对设备无可见效果)走 §18.13 F1 expectation_suspect
面板,形态教科书级——双源对账:
- conflict_shape=manual_vs_device
- sides:①device_context 原文"no sdns host method autotest1.com"(时间锚 15:08:30)
  ②manual"该命令用于删除指定域名的SDNS域名算法"(Chapter20.md:426 行锚)
- retrieval_receipt 检索回执
矛盾双方都带原文出处呈报,让用户判断产品缺陷 vs 期望错误——正确实现 §2.6.6 对称怀疑
推论(is-ought 矛盾不预判,第三源呈报)。**yzg 没触发过这类,dongkl 首次真实验证质量达标**。

## 发现 7(好):593573 s₀ 假阳未升格 bed

593573 attributor 判 h_s0(disp=reflow),但未落 diagnosis h_s0——disp=reflow 不匹配
bed_treatment_waiting(要 rerun_isolated/transient)+ attributor 补修,走 V 层重编不
bed。**s₀ 假阳不进床面板**,验证 §18.14 attributor 补修 + disp 门。

## dongkl ask 检查小结(截至归因收口)

**好(验证 §18.14/§18.13 设计)**:算法欠定数学题面优秀、14 fail 归因健康零 s₀ bed
假阳、expectation_suspect F1 双源对账面板优秀、defect_candidate 正确归类产品缺陷候选。
**问题(记录未改)**:command_existence 门语义盲区(worker 错误命令当版本缺失,发现 2/4)、
DNS 单标签超长 lint 盲区(发现 5,待确认)。

## 发现 8(核实 572708:F1 面板准确,但建议偏向历史 verified 的血统风险)

用户要求核实设备返回+excel。核实结论:
- **excel 编写正确**:step6 配置 host method autotest1 rr → step8 found → step10 no
  sdns host method autotest1 → step12 not_found → step13 found autotest2。标准
  "配置→found→删除→not_found"验证,断言方向对,非 worker 问题。
- **设备实际 no-op(实锤)**:step10 `no sdns host method autotest1.com` 后 step11
  `show sdns host method` 仍显示 `sdns host method "autotest1.com" "rr"`——条目未删,
  not_found 断言真 fail。
- **引擎归因准确**:真实产品缺陷(no sdns host method no-op,手册说删除),F1 双源对账
  呈报正确。

**风险(记录)**:引擎处置建议"改断言为 found(与 verified 前轮一致)"——verified 前轮
用 found 通过**可能本身是当年掩盖同一缺陷**(也接受了设备不删除)。拿历史 verified 当
建议依据=继承历史缺陷妥协,与 s₀ 投毒先例同型的判例血统风险。**正确处置是判缺陷**
(no sdns host method 不生效,报缺陷候选),非改 found 掩盖。F1 把裁决权交用户是对的,
但默认建议偏向 found 的倾向值得警惕(F1 建议不应默认锚历史 verified,尤其历史可能是
缺陷妥协)。

## 发现 9(核实 777976:算法分布被误判环境阻塞,attributor 依据与设备矛盾)

用户要求核实 env_blocked 判定。核实结论:**引擎误判,非环境问题**。设备返回:
- p1(172.16.35.213):Hit:1,dig 正常返回它(Success Num 1)——环境通、dig 工作;
- p2(172.16.35.231):Health UP 但 Hit:0(Fail Num 1/2)——成员健康,流量没轮转到;
- attribution 依据"routerb dig produced no output; environment/reachability failure"
  **与 p1 Hit:1 自相矛盾**(p1 命中证明 dig 有到达有解析,不可能"无输出")。

**真问题**:V 层算法分布欠定(rr/method 小样本全命中 p1、没轮转 p2),同族 593516
("10次dig仅1次到达")/593573("4次dig全返p1")。**引擎归错层**(E 环境阻塞 → 实为 V
算法分布),依据("dig no output")与设备实际(p1 Hit:1)矛盾。选项1"确认环境问题"会把
可修的算法分布问题当环境放弃。

**对照 572708(准确)vs 777976(误判)**:同批 attributor 一准一误——572708 双源对账
准确捕获真缺陷;777976 把算法分布(p2 Hit:0)误读成环境阻塞(dig 无输出)。误判根源:
attributor 未核对"p1 Hit:1 与 dig-no-output 矛盾"就下环境结论(LLM 归因未做内部
一致性检验)。这类"归因依据与设备回显自相矛盾"或可加机械后校验(attribution 的
env_blocked 依据 Hit:0,但同卷有其他 Hit:≥1 → 环境通,env_blocked 存疑)。留记录。

## 发现 10(核实 994986:执行主机配错被误判环境阻塞;env_blocked 系统性误判)

用户核实第二个 env_blocked。结论:**又是误判,非环境**。设备返回:
- 配置命令(sdns pool/host/method)正确发到 APV_0(172.16.35.70 设备 CLI);
- 验证步骤 `show sdns host pool` 配到 **console**,而 console 落 Linux 主机
  (`root@console:/home/test#`)→ Linux 无 `show` 命令 → "Command 'show' not found,
  apt install mailutils-mh..."。
- **真问题:worker 把设备 CLI show 配到了 Linux 触发机(执行主机/dispatch 错),
  非环境阻塞**(APV 设备正常)。应 V 层 reflow(show 改到 APV_0)。

**系统性发现:env_blocked 归因质量系统性差(连续 777976+994986 两判两误)**:
- 777976:算法分布(p2 Hit:0)误判环境(依据 dig 无输出,反证 p1 Hit:1);
- 994986:执行主机错(console/Linux)误判环境(依据 command not found,反证
  root@console:/home/test# 是 Linux 提示符非设备)。
attributor 看表面症状(dig 无输出/command not found)→ E 层结论,未深究真因,缺机械
兜底。**两者都有可机械检测的反证**:①env_blocked 依据 Hit:0 但同卷有 Hit:≥1 → 环境通;
②回显含 Linux 提示符(root@...:/...#)/apt install → dispatch 错非环境。可加 attribution
env_blocked 后校验(机械扫这些反证信号,矛盾则降级 V 层)。与 §18.14 attributor s₀ 机械
复核同型延伸。留记录,未改代码。

## dongkl ask 检查最终小结(截至用户核实的三个面板)

三个面板核实:1 准(572708 真缺陷,F1 双源对账准)、2 误(777976/994986 env_blocked
把 V 层误判 E 层)。**F1 机制本身好用,但 attributor LLM 归因质量不稳(尤其 env_blocked/
s₀ 这类需内部一致性检验的),需机械后校验兜底**。加上 command_existence 门盲区(发现2/4)、
DNS 标签 lint 盲区(发现5),本轮共 4 类值得修的问题,全部只记录未改代码。
