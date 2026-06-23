# yzg 脑图编译产物审计报告：厨师长(grade)判分 vs 框架实跑 vs 人工复核

> 2026-06-16。本报告**全部基于真实运行数据**,不凭记忆:
> - grade 完整判分理由:`/tmp/yzg_grade2.json`(26 个 case 直接调 `ist_compile_grade` fork 重跑,绕开主 agent 和 CLISink 截断)
> - 框架实跑裁决:`/tmp/yzg_run2_results.json` + 跳转机 `/home/test/apv_src/report/.../ist_staging_sdns/` 日志
> - excel 内容:`workspace/outputs/<autoid>/case.xlsx`(26 个 draft)
> - 合并产物:`workspace/outputs/yzg/case.xlsx`(26 case + 哨兵)

## 0. 结论先行(对"grade 过严"这一判断的更正)

我在拿到完整 grade 理由前,曾凭"读了几个断言"判断 **grade 判 CUT 过严、把合理的解析断言误杀**。读完 26 个完整判分理由后,**这个判断大部分是错的,需更正**:

- grade 的判分**不是**"凡是 dig 验解析 IP 就 PASS、凡是没验动态就 CUT"的粗暴标准。
- 真实标准是逐 check_point 打分(`compile_score`)+ 对照**手册行为**和**先例形态**,且明确区分"配置存在性检查"(弱)与"功能行为验证"(强),**最弱 check_point 拖垮全局**(整体 < 0.5 → CUT)。
- 我之前以为"被误杀"的 dig 验解析 IP 的 case(655154/655173/655188/655218/655233/655262 等),grade **全判了 PASS**——和我后来的人工判断一致。grade 没有误杀它们。

最终分布:**12 PASS / 14 CUT**。下文逐条对照,指出 grade **判对**的和**仍可商榷**的。

## 1. 三方对照总表

| autoid | grade | 框架实跑 | 说明 |
|---|---|---|---|
| 655154 | PASS | **fail** | grade 认断言质量达标;框架 fail 在 dig 没解析到 172.16.35.231(环境/解析链路,非断言错) |
| 655173 | PASS | fail | 同上(IPv6 listener) |
| 655188 | PASS | fail | 同上 |
| 655203 | **CUT** | **崩溃** | grade 点出"步骤2 `found sdns on` 冗余弱断言";框架因该悬空断言抛 TypeError 中断整包 |
| 655218 | PASS | no_log | 强动态断言(0.9+1.0)+ 先例支撑 |
| 655233 | PASS | no_log | dig 验具体解析内容,非状态码 |
| 655248 | CUT | no_log | grade:check1 静态配置检查弱;但 check2/3(dig 验后端 IP)强 |
| 655262 | PASS | no_log | compile_score overall=1.0 |
| 655276 | CUT | no_log | grade:仅验 NOERROR,未验"默认端口53不显示"的手册行为 |
| 655290 | CUT | no_log | grade:check2 仅 0.4 分,要求验自定义端口 10001 行为 |
| 667986 | PASS | no_log | found_times×16 强结构断言,有手册"最多16条"依据 |
| 668000 | CUT | no_log | grade:overall=0.0,未咬住"port 未保存"核心行为 |
| 668015 | CUT | no_log | grade:**步骤7 `not_found 53` 是伪断言**(手册说默认端口本就不显示,该断言永远成立) |
| 668030 | CUT | no_log | grade:要求 found(IP保存)+not_found(port53未保存)配对 |
| 668044 | PASS | no_log | grade:check2 `not_found 53` score=1.0,咬住需求 |
| 668059 | CUT | no_log | grade:全域名递归,步骤9 `baidu.com.` 弱,未验 A 记录具体 IP |
| 676594 | CUT | no_log | grade:`found flags: qr` 弱,建议改 `status: NOERROR` |
| 676612 | PASS | no_log | grade:forward_only 转发,NOERROR 能区分成功/失败,0.7 放行 |
| 676626 | CUT | no_log | grade:跨设备递归,仅验 recursion 开关,未验真能解析 |
| 676640 | PASS | no_log | grade:两断言覆盖"解析IP正确+NOERROR"两维度 |
| 676654 | CUT | no_log | grade:zone forward,断言未验转发实际生效 |
| 676668 | PASS | no_log | grade:PASS 附改进意见(建议验具体解析结果) |
| 681539 | CUT | no_log | grade:跨设备,`found listener` 是配置验证非行为验证 |
| 681556 | CUT | no_log | grade:4 条静态配置检查(0.3)+ 2 条强(0.9),整体被弱项拖垮 |
| 681571 | CUT | no_log | grade:CUT/abstain |
| 681588 | PASS | no_log | grade:dig TCP 验 found 172.16.35.231,先例一致 |

注:框架实跑因 655203 崩溃中断,仅前 4 个有真实裁决,后 22 个 no_log(未执行)。

## 2. grade 判分的真实逻辑(从理由原文提炼)

grade 不是单一标准,而是多维度:

1. **逐 check_point 打分**(`compile_score`,0~1):配置存在性检查 ≈ 0.3(弱),功能行为验证(dig 验解析 IP/状态码)≈ 0.9~1.0(强)。
2. **最弱 check_point 拖垮全局**:整体分由弱项决定,有一条纯静态弱断言且无强断言补足 → 整体 < 0.5 → CUT。
3. **对照手册行为**:多次引 `10.5_cli__part2` 手册具体行号(如第7405行"write mem 后默认端口53不保存"、第7416行"默认端口53不显示")判断断言是否抓住手册描述的关键行为。
4. **对照先例形态**:反复引 `sdns_listener.xlsx`/`sdns_listener_tcp.xlsx`/`sdns_forward-test.xlsx` 等先例,断言形态与先例一致才认。
5. **识别"伪断言"**:668015 的 `not_found "sdns listener ...53"` 被 grade 点破是**永远成立的空话**(手册说默认端口本就不显示),这是很精准的判断。

## 3. 我之前判断与 grade 的冲突:谁对谁错

| 我之前的判断 | grade 实际 | 谁对 |
|---|---|---|
| "dig 验 172.16.35.231 是合理断言,grade 误杀" | grade 对这些**全判 PASS**(655154/173/188/218/233/262/681588) | **grade 对,我之前担心的误杀不存在** |
| "只验 status:NOERROR 是弱断言该 CUT" | grade 区分场景:simple 解析场景验 NOERROR+解析IP 算够(PASS);但单独只 NOERROR 不验输出值的判 CUT(655276) | **基本一致,grade 更细** |
| "16 个 CUT 偏高、过严" | 实际 14 CUT,且每个都有手册/先例依据(端口未验、伪断言、递归未验解析、配置存在性拖垮) | **我之前"过严"的判断错了——CUT 大多判得有理有据** |
| "655203 断言悬空崩框架" | grade 也判 CUT,理由是"步骤2 found sdns on 冗余弱断言" | **一致,且 grade 在上机前就抓到了** |

**关键更正**:我之前"grade 过严、误杀合理断言"的判断,在拿到完整理由后**被推翻**。grade 实际判得相当准——它没有误杀 dig 解析断言,CUT 的 14 个大多有手册/先例支撑的实质理由。我之前的错误源于**只看了断言表面、没看 grade 的完整理由就下结论**。

## 4. grade 仍可商榷的点(少数)

并非全无可议,但属"严格但不算错":

- **655248**:check2/check3 已是强断言(dig 验后端 IP),仅因 check1(配置存在性 0.3)被"最弱拖垮全局"判 CUT。这条**偏严**——已有强断言覆盖核心行为时,一条配置存在性前置检查是否该把整体拖到 CUT,可商榷。
- **681556**:同理,2 条强断言(0.9)+ 4 条配置存在性(0.3),被弱项拖垮。
- **"最弱 check_point 拖垮全局"规则**:对"强断言已覆盖核心行为 + 附带几条无害的配置前置检查"的 case 偏严。可考虑改为"只要有一条强断言真覆盖核心行为即不 CUT,弱前置检查降级为提示"。

## 5. 框架实跑暴露的、与 grade 正交的问题

grade 判的是**断言质量**,框架实跑暴露的是**能否上机跑通**,两者正交:

- **655203 悬空断言崩整包**(check_point 紧跟无回显的配置命令 → TypeError → 中断后续 22 case):grade 判了 CUT(认它弱),但**没预判到它会崩框架**。这提示:除 grade 断言质量审批外,emit 阶段需加**结构校验门**(check_point 前必须有产生输出的命令),否则悬空断言会让合并 xlsx 整包挂掉。
- **前 3 个 PASS 的 case 框架实跑 fail**(dig 没解析到 172.16.35.231):grade 判 PASS 没错(断言质量好、IP 可溯源),fail 是**环境/解析链路**问题(dig 无有效响应),不是断言错。这印证 grade(断言质量)与上机(能否跑通)解耦的合理性——断言写得对,不代表当前环境能跑通。

## 6. 待办(基于本报告的事实)

1. **emit 加结构校验门**:check_point 前一条必须是 show/dig 等产出命令,挡住悬空断言(根治 655203 类崩溃)。
2. **grade "最弱拖垮全局"规则微调**:有强断言覆盖核心行为时,配置存在性前置检查不应单独触发 CUT(影响 655248/681556 类)。
3. **dig 解析 fail 归因**:前 3 个 PASS case 上机 fail 在 dig 解析,需查是环境(后端 172.16.35.231 服务/网络)还是 sdns 配置链路在设备上未生效——属环境侧,与编译质量解耦。
4. **合并 xlsx 跑法**:框架"一个 case 崩中断整包",需 case 间隔离或先剔除会崩的 case 才能拿到 26 个完整 verdict。
