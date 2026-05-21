# 测试知识地图

`knowledge/data/markdown/qa/` 下 16 份测试相关文件按用途分类。**评审时不要全读**，按本表按需取。

## 关键约束

> 这些是**测试知识参考资料**。读完后由你自己提炼"该测什么、用什么字段、怎么组织"。**禁止**按维度词清单（并发/超时/日志/权限/边界/upgrade/双语...）强行打勾——评审里出现的每个维度都必须能追溯到 Test Strategy / 产品文档 / 缺陷描述里的具体出处。

---

## A. 用例字段规范模板（5 份）

读这些是为了拿到"用例应该长什么样"的硬约束（必填字段 / 用例类型 / 优先级标记规则）。

| 文件 | 行数 | 用途 |
|---|---|---|
| `BugID-功能名称.md` | 56 | **标准 17 字段集**——所有用例文件的字段对照基准 |
| `XXX子功能 CLI 测试用例.md` | 37 | CLI 类用例的字段约束 |
| `XXX子功能 安全基线测试用例.md` | 35 | 安全类用例的字段约束 |
| `XXX子功能压力测试用例.md` | 21 | 压力类用例的字段约束（含 CPU 阈值 / 持续时间约定） |
| `YYY子功能测试用例.md` | 25 | 通用功能用例的字段约束 |

**读法**：评审任何用例都先看 `BugID-功能名称.md` 的字段头，然后按用例类型挑读对应模板。

---

## B. 测试方法论（2 份）

读这些是为了拿到"该测什么维度"的启发——**不是清单，是案例**。

| 文件 | 行数 | 适用场景 |
|---|---|---|
| `Test Strategy_HTTP protocol.md` | 221 | HTTP 协议层评审参考（cookie / persistence / session 类优先看这份） |
| `Test Strategy SLB_HTTP2_phaseII.md` | 583 | HTTP/2 + SLB 复杂功能评审参考（含测试范围 / 优先级 / 反向依赖） |

**读法**：grep 出跟当前 BUG 关键词相关的段落。你提的每个评审维度都应该能在这些文件里找到出处。

---

## C. 测试范围 / 优先级判定（1 份）

| 文件 | 用途 |
|---|---|
| `HTTP2 phase II test scope & priority.md` | 测试范围圈定 + 优先级判定的方法论参考 |

---

## D. 历史被评审用例（按 feature 域分类）

读这些是为了**对照同类功能怎么组织章节、怎么标记 Test Types、缺陷回归用例长什么样**。

### Cookie / 会话保持
- `Test List_Cookietamper.md` — Cookie 篡改测试，cookie 类评审优先参考
- `Test List bug-to-case 121100 Cookie会话保持加密.md` — Cookie 加密（即当前评审目标，不要循环读）

### HTTP / 协议
- `HTTPprotocal test list.md` — HTTP 协议测试集
- `Test list_HC.md` — HC（Hash Cookie 或 Health Check）测试

### HTTP/2 系列
- `Test List HTTP2.0_phaseII.md`
- `Test List HTTP_2_new_cli.md`
- `HTTP2 test in phase II_jiangyz.md`
- `HTTP2 phase II test scope & priority.md`（已在 C 节列出）
- `Test_list_Cache_HTTP2.md`

**读法**：`qa_deepagent_grep` 找跟当前 BUG 关键词最接近的文件，再分页 `read_file` 看章节组织。

---

## 评审参考映射

按 BUG 关键词快速定位优先读什么：

- **cookie / ircookie / session / persistence / aes / 加密**
  - 字段模板：`BugID-功能名称.md` + `XXX子功能 CLI 测试用例.md`
  - 方法论：`Test Strategy_HTTP protocol.md`
  - 同类用例：`Test List_Cookietamper.md`

- **http2 / h2 / fasthttp**
  - 字段模板：`BugID-功能名称.md` + `XXX子功能 CLI 测试用例.md`
  - 方法论：`Test Strategy SLB_HTTP2_phaseII.md`
  - 范围/优先级：`HTTP2 phase II test scope & priority.md`
  - 同类用例：`Test List HTTP2.0_phaseII.md` / `Test List HTTP_2_new_cli.md`

- **cache**
  - 同类用例：`Test_list_Cache_HTTP2.md`
  - 方法论：先看 `Test Strategy SLB_HTTP2_phaseII.md`（含 cache 段）

- **stress / 压力 / 性能**
  - 字段模板：`XXX子功能压力测试用例.md`（CPU 阈值 / 持续时间约定）

- **安全 / security**
  - 字段模板：`XXX子功能 安全基线测试用例.md`
