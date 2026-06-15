# 用例编译流水线的线性代数化（零训练版）

这份笔记把“配对修正后的三空间”与“零训练线代骨架”接起来，目标不是再堆公式，而是把每个公式放回正确的定义域，并用当前仓库里已经跑出的数字约束叙述。

## 0. 三个空间

| 空间 | 含义 | 住在这里的量 |
| --- | --- | --- |
| `I` | 意图空间：脑图层级路径、算法类型、动作类型、版本语义 | 相似度、树核、OOD、聚类、路由 |
| `T` | 输出空间：`case.xlsx` 的命令、断言、文法、设备 verdict | 命令词矩阵、SVD、checker、语法约束 |
| `(I,T)` | 配对 / 映射：同一 `autoid` 的意图与生成输出 | `phi* : I -> T`、覆盖、校准对象、rework 成本 |

核心修正只有一句：**相似性那一族不该住在 `T`，而该住在 `I`。**

## 1. 记号

- 命令词表 `V`，`n = |V|`。
- 先例库 `m` 条。
- 单条输出用例表示为向量 `x \in R^n`。
- 先例库矩阵 `P \in R^{m x n}`，行是先例，列是命令词。
- 意图节点集合记为 `{I_a}`，输出集合记为 `{T_a}`，其中 `a` 是 `autoid`。

## 2. `T` 空间：输出向量化

把 Jaccard 的集合表示换成向量空间：

```tex
x_j = tf(j) \cdot log(m / df(j))
```

于是 `P` 成为经典词-文档矩阵。后续在 `T` 空间上讨论的量包括：

- token 级相似度；
- 命令空间的 SVD / 低秩近似；
- checker 可否被线性系统替代；
- 文法与语法合法性。

## 3. `I` 空间：树核、聚类、OOD

意图不是词袋，而是层级路径树。当前采用路径前缀核：

```tex
kappa(I_a, I_b) = sum_{k <= LCP(I_a, I_b)} lambda^k
```

归一化后得到 Gram 矩阵 `K_I`。

### 当前实证

来自 [intent_space.py](/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/workspace/outputs/_research_linalg/intent_space.py)：

- 意图节点共 `113` 个。
- 树核 Gram 的有效秩 `r_eff = 4.8`。
- 特征值前 12 个为 `[41.76, 21.66, 19.45, 5.62, 3.51, ...]`。
- 50% / 80% / 90% 能量分别只需 `k = 2 / 5 / 16` 个主成分。
- `eps = 0.1` 时，`109/113` 个意图有近邻先例。
- `eps = 0.2` 时，`92/113` 个意图有近邻先例。

### 结论

- `I` 空间是低秩的。
- “范式数少”这个判断成立，但它成立在 `I`，不成立在 `T`。
- 路由和 conformal OOD 应先在 `I` 上做，而不是在命令 token 上做。

## 4. `T` 空间：命令矩阵、内积、SVD

在输出空间上，先例库矩阵为：

```tex
P = U Sigma V^T
P_k = U_k Sigma_k V_k^T
```

相似度用内积或 cos：

```tex
cos(x,y) = <x,y> / (||x||_2 ||y||_2)
K_T = P P^T
```

### 当前实证

来自 [analyze.py](/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/workspace/outputs/_research_linalg/analyze.py)：

- 先例库可用文档 `214 / 214`。
- 本轮 case 可用 `53 / 53`。
- 命令词表维数 `n = 724`。
- 命令空间有效秩 `r_eff = 68.6`。
- 50% / 80% / 90% / 95% 能量需 `k = 8 / 26 / 44 / 60`。

### 结论

- `T` 空间不是低秩小空间。
- “68 种正交范式”如果说的是命令空间几何，基本成立；但它不是意图范式数。
- 快路径若直接在 `T` 上做“相似即复用”，覆盖面不会像 `I` 空间那样乐观。

## 5. `(I,T)`：映射 `phi*`

真正要研究的是配对映射：

```tex
phi* : I -> T
```

如果 `phi*` 光滑，则可按意图相似度借整骨架；如果不光滑，则只能把 `T` 拆解成更稳定的子部分。

### 当前实证

来自 [intent_space.py](/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/workspace/outputs/_research_linalg/intent_space.py) 与 [smoothness_refine.py](/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/workspace/outputs/_research_linalg/smoothness_refine.py)：

- 已配对 `(I,T)` 共 `38` 对。
- 全 token 相似度相关系数 `rho = -0.078`。
- 判别 token（剥样板）`rho = 0.171`。
- 命令骨架（命令头去值）`rho = 0.157`。

### 结论

- `phi*` 不是强光滑映射。
- 剥掉样板后出现弱正相关，说明“完全不相关”也不准确。
- 可借的是局部模板与骨架锚点，不可借的是整例插值。

更稳妥的分解是：

```tex
T(I) = Template[paradigm(I)] \oplus Values[params(I), dyn_model(I)]
```

其中：

- `Template` 由范式决定，稳定但信息量低；
- `Values` 由具体参数、方法规则、状态机事件决定，不能只靠近邻抄写。

## 6. `T` 空间上的 OOD：残差而非神话双峰

若把新 case 投影到命令主子空间：

```tex
x_hat = V_k V_k^T x
r = x - x_hat
d_OOD(x) = ||r||_2
```

阈值取先例自身残差分位数：

```tex
tau_eps = Quantile_{1-eps}(||r_i||_2)
```

### 当前实证

来自 [analyze.py](/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/workspace/outputs/_research_linalg/analyze.py)：

- `k = 10` 时，先例 90% 分位阈值 `tau = 0.966`，本轮 case 只有 `2/53 = 4%` 落在阈值内。
- `k = 20` 时，`tau = 0.786`，本轮 case 有 `19/53 = 36%` 落在阈值内。
- 残差分布整体偏高，不是“近零一团 + 长尾”的干净双峰。

### 结论

- 命令空间 OOD 不能写成很强的“双峰快慢分层”。
- 更像是：只有一部分 case 能进入快路径，其余仍需中路径或慢路径。
- 这和 `I` 空间的高自相似不矛盾，反而说明 `phi*` 是瓶颈。

## 7. 模板实例化：指派 / 置换矩阵

高相似 case 不应整轮重写，而应解一个对齐问题：

```tex
Pi* = argmin_{Pi in P_n} <C, Pi>
```

这里 `P_n` 是置换矩阵集，`C_ij` 是步语义距离。连续松弛到 Birkhoff 多胞形后可用匈牙利算法或线性规划求解。

现阶段这条数学是合理的，但还没有仓库内的成体系实证。

## 8. checker：线性动力系统能吃掉一部分，但不是全部

对 rr / wrr / 轮询类断言，理想形式是状态转移：

```tex
P_cyc in R^{p x p}
s_{t+1} = P_cyc s_t
h_k = sum_{t=0}^{k-1} s_t
```

理想 rr 的累积命中：

```tex
h_k[i] = floor((k - i - 1) / p) + 1
```

### 当前实证

来自 [rr_timevar.py](/Users/jiangyongze/Library/CloudStorage/SynologyDrive-home/Project/InfoTest_Engine/workspace/outputs/_research_linalg/rr_timevar.py)：

- clean case 逐 dig 推演复现 `7/9`。
- 全部 rr-Hit case 总复现 `10/21 = 48%`。

### 结论

- “期望值属于确定性状态机”这个方向成立。
- 但当前模型还不足以写成“完全闭式覆盖”，因为事件抽取和状态语义还没补齐。

## 9. 置信校准：`C -> O` 的单调投影

若已有上机 oracle 标签 `(c_i, o_i)`，则校准不是训模型，而是一维单调回归：

```tex
g* = argmin_{g up} sum_i w_i (g(c_i) - o_i)^2
```

这就是 isotonic regression。校准后 `g(c)` 才能被解释成：

```tex
P(good | c)
```

这里的 `good` 应该定义为：

```tex
good(I,T) = O(T) /\ Cov(T,I)
```

即 verdict 与覆盖同时成立。没有 `I`，`Cov(T,I)` 无法定义。

## 10. 覆盖：`Cov(T,I)` 才补上 `O` 缺的那一轴

把断言集看作行为空间里的向量，需求行为子空间记为 `B`，则覆盖定义为：

```tex
Cov(T,I) = dim(span(A) cap B) / dim(B)
```

弱断言本质上是秩亏方向，对 `Cov` 贡献很小。

这条公式仍需后续把“断言向量化”具体落地；但就定义域而言，它只能住在 `(I,T)`，不能只住在 `T`。

## 11. 合成后的零训练骨架

```text
I --树核/聚类/OOD--> 范式路由
                 \
                  \-> 进入 (I,T) 映射
                       -> 小残差: 模板 + 指派 + 线性 checker
                       -> 中残差: LLM 填语义槽, 文法 / 覆盖夹紧
                       -> 大残差: 全力 LLM, 沉淀新配对样本

grade:
  verdict O(T)
  + 覆盖 Cov(T,I)
  + 校准 g(c)
```

## 12. 当前最稳的结论

- 最高杠杆点没变：`C -> O` 的 isotonic 校准仍然是最便宜、最值钱的一刀。
- 真正被配对修正改变的是定义域：相似度、核、OOD、聚类、路由应搬回 `I`。
- `I` 低秩，`T` 高秩，`phi*` 只弱光滑。
- 因此快路径不能是“按意图相似直接抄整 case”，而应是“按意图范式选模板，再由参数与 checker 补足”。

## 13. 下一步实验

- 每方法线性动力模型全集。
- checker 分类率与误差来源。
- `C -> O` 的 isotonic 校准与 reliability curve。
- `Cov(T,I)` 的断言向量化与秩计算。
