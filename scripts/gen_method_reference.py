#!/usr/bin/env python3
"""生成 worker 可达的框架方法参考投影（#58 FINDING #1 修法·方案 a PROJECT）。

问题:worker fork 沙箱不含 mirror 源码(mirror 是 2 文件白名单读根,ssl_comm.py/apv_action.py
不在内),且 references/contracts.md 在 `main/`(_PLATFORM_DENIED)对 fork 不可达——故 #52 写在
contracts §SSL 的方法签名/动作注册表/S1-S5 从未到达 worker(FINDING #1)。

修法:把 worker 需要的**框架方法数据**投影进沙箱可达的 `knowledge/data/compile_ref/`
(与 command_inventory/domain_grammar 同模式,数据按引用流、worker fs_read 得到)。

**生成式**(机械部分零手抄漂移):
- cert 方法签名 ← 解析 mirror `lib/apv/ssl_comm.py` 的 def 签名
- execute 动作注册表 ← 复用 #56 `structural_gate._execute_action_registry`(command_function_mapping ∪ synonyms)
**策展式**(语义/行为观察,稳定):S1-S5 静默失败面 / dispatch 骨架 / server hosts / notes
——源自 references/contracts.md §SSL(LLM-Eng #52)+ #50-A 方法卡。

用法:`python scripts/gen_method_reference.py`(改 mirror 后重跑);漂移守门测比对生成态。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_OUT = _ROOT / "knowledge/data/compile_ref/method_reference.json"

# 证书族方法名前缀(#50-A 确认:25 base + 12 _tftp)
_CERT_DEF_RE = re.compile(
    r"def (import[A-Za-z_]+|csr[A-Za-z]+|ecc[A-Za-z]+|sm2[A-Za-z]+|activeCert)\(self,\s*([^)]*)\):"
)


def _parse_cert_methods() -> dict:
    """解析 ssl_comm.py 证书方法签名(必需/可选参),生成式、零手抄。"""
    from main.ist_core.tools.device.structural_gate import _mirror_src
    src = _mirror_src("lib/apv/ssl_comm.py")
    out: dict[str, dict] = {}
    for m in _CERT_DEF_RE.finditer(src):
        name, params = m.group(1), m.group(2)
        plist = [p.strip() for p in params.split(",") if p.strip()]
        required = [p for p in plist if "=" not in p]
        optional = [p.split("=")[0].strip() for p in plist if "=" in p]
        out[name] = {"required": required, "optional": optional}
    return out


def _execute_actions() -> dict:
    """复用 #56 注册表解析:{归一化名: 原名}——command_function_mapping ∪ synonyms。"""
    from main.ist_core.tools.device.structural_gate import _execute_action_registry
    reg = _execute_action_registry()
    # 只暴露原名集合(worker 逐字对齐用),按名排序
    return {"exact_action_names": sorted(set(reg.values())),
            "note": "F=execute 的 G 动作名必须是本集精确成员(全角冒号前段);非精确会落 "
                    "fuzzy≥0.8 静默派发、可语义反转(#56 门在 emit 期拒非精确名)。"}


# ── 策展部分(语义/行为,源 contracts §SSL + #50-A 卡;稳定、非机械可生成)──────────
_CURATED = {
    "dispatch_skeleton": {
        "E_F_G_H_I": "getattr(E_obj, F)(*positional, **kwargs);G 逗号分参(引号感知);"
                     "H=把返回值存进命名寄存器(device 步)/取期望值(check_point 步);"
                     "I=把变量或对象.属性 .format() 注入 G 首参(须带 {} 占位)。",
        "source": "mirror test_xlsx.py:280-336",
    },
    "cert_arity_notes": {
        "rsa_import": "RSA importKey/importCert = 2 参 <vhost>,<file_path>(#50 CC1)",
        "sm2_import": "SM2 sm2ImportKey/Cert = 3 参 <keyType>,<vhost>,<file_path>;keyType="
                      "signkey/enckey(签名)或 signcertificate/enccertificate——SM2 国密双证书体系;"
                      "参数个数写错崩整卷(#50 CC2,8 金标准行核对)。",
        "csr_subject": "CSR subject 硬编码 US/CA/San Jose/clickarray/qa,不可参数化。",
        "file_branch": "文件名 .key/.crt/.pem 结尾→本地读文件内联粘贴;否则→TFTP 从 "
                       "172.16.35.215 取。金标准全走本地分支(#50 CC3),床就绪只需本地 cert 树。",
        "activate_dependency": "ssl activate certificate <h> 依赖先有 ssl host virtual <h>"
                               "(文法门 ssl_cert_activate_needs_host_define 已查)。",
    },
    # 方法行为注(锚一致:同一事实在 footprint decision_rule 与本投影两处出现,共引同一 source
    # 行防跨边界漂移——#58 Design 协调):importCert 自动 activate 事实锚 ssl_comm.py:153-154,
    # 与 LLM-Eng footprint 节点 ssl.activate.certificate 的 decision_rule 同锚。
    "cert_behavior_notes": {
        "importCert": {"note": "导入后**自动 ssl activate certificate + YES**,勿再手动 activate",
                       "source": "ssl_comm.py:153-154"},
        "importRealCert": {"note": "同 importCert,自动 activate", "source": "ssl_comm.py:286-287"},
        "sm2ImportCert": {"note": "自动 activate", "source": "ssl_comm.py:622-623"},
    },
    "server_trigger_hosts": {
        "hosts": ["server213", "server231", "server232", "routera", "routerb",
                  "clientc", "clientd", "cliente", "console"],
        "contract": "E=test_env,F=serverNNN;SSH 到 config [env] 段该逻辑名的 IP(user test/click1),"
                    "G=后端 shell 命令(起停真实服务器造 UP/DOWN);ip addr/route add 自动记账、"
                    "case 尾框架自动恢复(勿自行 del)。",
        "source": "mirror env.py:66-98 + ssh_server.py:34-118",
    },
    "silent_failure_faces": [
        {"id": "S1", "mechanism": "证书/密钥文件缺→print+return,import 没发生、不抛错(假象=断言错)",
         "source": "ssl_comm.py:102-104"},
        {"id": "S2", "mechanism": "execute 动作名不中/fuzzy≥0.8 误派→None(可派到语义反义 func)",
         "source": "dic_operation.py:72/:79-80"},
        {"id": "S3", "mechanism": "server/read_until 超时→返回部分输出、非抛错(断言搜残缺窗口假 fail)",
         "source": "ssh_server.py:91"},
        {"id": "S4", "mechanism": "TFTP 源 172.16.35.215 不可达/文件缺(金标准不走此分支,床需本地 cert 树)",
         "source": "ssl_comm.py *_tftp"},
        {"id": "S5", "mechanism": "H 存 None(多数 SSL import 无 return)→后续 H 引用无意义",
         "source": "test_xlsx.py:332-336"},
    ],
    "attribution_note": "上机 fail 归因时,先用 S1-S5 把 harness 静默失败与真实设备行为分开"
                        "——harness 静默失败伪装成 V 层断言错(#50-A / #52 attributor S1-S5)。",
}


def build() -> dict:
    return {
        "_meta": {
            "purpose": "worker-reachable projection of framework method arg-signatures + execute "
                       "action registry + silent-failure faces (mirror NOT in worker sandbox; "
                       "this is the fs_read-able data-by-reference surface, #58 FINDING #1 fix a)",
            "regenerate": "python scripts/gen_method_reference.py",
            "generated_parts": ["cert_methods", "execute_actions"],
            "curated_parts": list(_CURATED.keys()),
            "generated_from": "mirror lib/apv/ssl_comm.py + apv_action.py/client_action.py + synonyms",
        },
        "cert_methods": _parse_cert_methods(),
        "execute_actions": _execute_actions(),
        **_CURATED,
    }


def main() -> None:
    data = build()
    _OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {_OUT} — cert_methods={len(data['cert_methods'])} "
          f"exact_actions={len(data['execute_actions']['exact_action_names'])}")


if __name__ == "__main__":
    main()
