# 编译红线评审 — 任务 #61（SSL-003 durable fix：全角逗号归一化 + footprint surfacing）

> 2026-07-19 · **leader 亲评**（redline61 子 agent 未落文件/发信通道不通，同 redline56/58；为不阻塞 SSL saga 收官由 leader 亲核 redline-sensitive 面；只读评审）。
> 前置：Theory P（auto-normalize 歧义性判据 + surfacing footprint 模型）已过。本评为 redline 专项。

## 总体：PASS（五项检查全过，红线零命中）

### 检查 1：零写死设备/领域命令 — PASS
- comma normalize 是**纯字符替换** `init_g.replace("，", ",")` / `_s["G"].replace("，", ",")`——领域无关、无写死命令、无 SSL 专属逻辑（对任意 G 值生效）。

### 检查 2：无 observe-then-assert / 不碰断言 — PASS（核心）
- 代码**显式跳过 check_point**：`if not isinstance(_s, dict) or str(_s.get("E","")).strip() == "check_point": continue`——check_point 断言 pattern 不归一化（断言位可能匹配设备回显里的全角字符、有歧义，保守不动）。只归一化 init_g + 非 check_point 步 G。

### 检查 3：确定性/安全 — PASS
- `，`→`,` 是 1:1 替换。注释论证 dispatch G 全 ASCII、命令参数位全角逗号恒为误打无合法用途（唯一映射）。范围限 init_g + 非 check_point 步 G，不误伤断言。device-verified 真 blocker（003 rows 32-34 `vh1，cert/...` importKey TypeError 铁证）。

### 检查 4：可观测 signal — PASS
- `emit_signal("fullwidth_comma_normalized", autoid, source="compile_emit", count=_fw_comma)`——注册入闭集（signals.py +3）、健康输入恒零、告警不静默。emit 包 try/except 落盘失败仅 debug log、不崩 emit（健壮）。

### 检查 5：placement + surfacing 渲染机制非数据 — PASS
- comma normalize 置于 init_rows 构建与各门之前（门看归一后值）。
- footprint surfacing（footprint_lookup.py）：父查浮现子 known_issue 摘要+指针（issues[:3]+「+N more」，详情引导直查叶）=数据按引用、非内联全文（Theory 主审确认）。

## 结论
#61 五项红线检查全 PASS，红线零命中。四关=Theory P + 待 Design + redline P（leader 亲评）+ leader 权威 pytest → 原子 commit → 干净重编 003。
