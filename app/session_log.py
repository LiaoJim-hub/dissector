# -*- coding: utf-8 -*-
r"""`session_log.py` —— **会话侧持久层**（装载件 §13.2 的七项），harness 代算。

★★ 三个落点，别混（持有方 2026-10-06 逐字澄清）

    ① **正文落款** —— 本轮可见、随对话走。**这是展示**。
    ② ★★ **会话侧持久层** —— 跨轮，**唯一能被对账的地方**（A3 的载体）。**这是账**。
    ③ **事件类**（裁剪 / 补位 / 错位 / 自检触发 / 降级）—— ★ **标注**，**不单独开账**，
       写进②的同一轮记录里。

★★★ 故本件就是那个②。它只做三件事：

    1. **七项**（§13.2 逐字）：`材料指纹 · 位集 · 位来源 · 层 · 是否层判不明 · M4 反方条件 · 落款形态(1-5)`
    2. **事件标注**（§13.2 那三类 + 持有方列的五个）也在**同一条**里
    3. **fail-closed**：能从落款机械提取的字段由本件填；**提不出的写 `undeclared`**，
       ★ **不许静默留空**（空数组会被下游读成"一切正常"）

★ 三条硬规（§13.2 逐字，都实现了）

    · **落款形态 4/5 也进账**，`位集` 写空 —— ★ **"没走位"本身是数据**
    · **不落材料原文** —— 只落 `长度 + 首 20 字`（＋其 sha256）
    · **探针三态不许合并**：`会话侧：无持久层（探针已跑）` ≠ `装机前提：未执行`
      ⇒ 故本件主动**证明自己能写能读**（见 `--probe`），由读数本身说话，不靠模型自报

★ 用法

    python session_log.py --selftest     # 正反两向（含形态 4/5、不落原文、undeclared）
    python session_log.py --probe        # ★ 探针：写→读回→删（证明持久层可用）
    python session_log.py --tail 10      # 看最近 10 轮
    python session_log.py --report       # §13.2 命中率与七项齐全度
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import pathlib
import re
import sys
import time

# [atomic-io-import:BEGIN]
# ★ B-35/B-37：原子追加与原子替换（持锁，防丢行/防半截文件）
try:
    import atomic_io
except Exception as _e:                                   # noqa: BLE001
    # ★ **不静默降级**：明说回退到了无锁写入，并给出原因
    atomic_io = None                                      # type: ignore[assignment]
    import sys as _sys
    print("[atomic_io] ★ 不可用（{0}: {1}）⇒ 回退到**无锁**写入，并发下可能丢行".format(
        type(_e).__name__, _e), file=_sys.stderr)
# [atomic-io-import:END]

# [atomic-io-fallback:BEGIN]
if atomic_io is None:                                     # ★ 回退（已在上方明确告警）
    def _append_line_fallback(_p, _o):
        with open(_p, "a", encoding="utf-8", newline="\n") as _f:
            _f.write(json.dumps(_o, ensure_ascii=False) + "\n")
    class _AI:                                            # 极简替身，只补被用到的两个函数
        append_line = staticmethod(_append_line_fallback)
        @staticmethod
        def write_json_atomic(_p, _o, indent=1):
            pathlib.Path(_p).write_text(json.dumps(_o, ensure_ascii=False, indent=indent),
                                        encoding="utf-8")
    atomic_io = _AI()                                     # type: ignore[assignment]
# [atomic-io-fallback:END]



try:
    sys.stdout.reconfigure(errors="backslashreplace")           # type: ignore[union-attr]
except Exception:                                               # noqa: BLE001
    pass

APP = pathlib.Path(__file__).resolve().parent
# ★ 本外发版：账在 **app\ 外面**（与 data\ 同级）—— ★ 整包替换式升级不许覆盖使用者的账。
HIST = APP.parent / "history"
LOG = HIST / "session_log.jsonl"
PROBE = HIST / ".probe_session_log.jsonl"     # ★ 探针专用，用完即删

#: §13.2 那七项（**顺序照逐字**，报告里也照这个顺序显示）
FIELDS = ("材料指纹", "位集", "位来源", "层", "是否层判不明", "M4 反方条件", "落款形态")

#: 落款五形态（§13.1；本件只需能区分 4/5 与前三）
FORM_NAMES = {
    1: "常态·走过位",
    2: "自检触发",
    3: "护根模式",
    4: "最小入口档（位集为空）",
    5: "不适用档（位集为空）",
}

#: 事件类的五个（持有方逐字：裁剪 / 补位 / 错位 / 自检触发 / 降级）
EVENT_NAMES = ("裁剪", "补位", "错位", "自检触发", "降级")


# ---------------------------------------------------------------------------
# 一、从落款机械提取（harness 代算，不靠模型自报）
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 〇、★★ 把落款解析与判据**委派给正本指定的可执行底**（2026-10-06 优化机制层）
# ---------------------------------------------------------------------------
#
# ★★ 为什么改（本轮优化的核心）
#
#   本件原先**自己写了一整套落款解析**（`footer_region` + `_find_field` + `_clean_layer` + 自建 `_PUNCT`）。
#   而正本 `装载件.md` §13.4 明写它有一份**可执行底**：`checks\落款校验.py`（25,233 B），
#   且正本 §0 的铁律是「**与代码冲突时以代码为准**」。
#   ⇒ 于是同一份落款被**两套正则**解析、被**两套口径**归一化：
#        · 它 `normalize()` 用 `unicodedata.category(ch).startswith("P")` 去标点
#        · `capability_ledger` 用自建 `_PUNCT` 表
#     ★ 这正是本体系记过多次的失效形态：**第二份实现各自漂移**。
#
#   实测缺口（改之前量的）：它 `parse_signature` 取 **12** 个键，我**不取其中 11 个**；
#     §13.4 八条判据在我账上 **0/35 可判** ⇒ 判据只能绕回 `sessions.json` 重解析一遍。
#
#   ⇒ 优化：**解析与判据一律委派**；本件只负责"落账"（append-only）这一件事，
#     并把 §13.4 八条判据的**读数记进账** ⇒ 判据从此能**直接建在会话侧账上**。
#
# ★ 载入手法与 `direction_history.py` 载入 `direction_state.py` 同：
#   模块名**不下划线开头**（`spec_from_file_location` 会返回 None）· **先放 `sys.modules` 再 exec**。

CHECK_PATHS = [
    # ★ 本外发版：判据底**随包**（app\checks\）—— ★ 原版那条指向**作者机器**的绝对路径已去。
    APP / "checks" / "落款校验.py",
]
_check_mod = None


def load_check():
    """import 正本指定的可执行底。★ 一个都找不到 ⇒ **显式报错**（不静默降级）。"""
    global _check_mod
    if _check_mod is not None:
        return _check_mod
    tried = []
    for p in CHECK_PATHS:
        tried.append(str(p))
        if not p.exists():
            continue
        spec = importlib.util.spec_from_file_location("luokuan_check", p)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules["luokuan_check"] = mod
        spec.loader.exec_module(mod)
        _check_mod = mod
        return mod
    raise FileNotFoundError(
        "找不到正本指定的可执行底 `checks\\落款校验.py`，已试：\n  " + "\n  ".join(tried))


def check_meta() -> dict:
    """★ **口径回显**：判据底自己的 profile / 阈值 / 映射表指纹 —— **原样取，不自己编**。"""
    c = load_check()
    return {
        "check_src": str(next((p for p in CHECK_PATHS if p.exists()), "")),
        "profile_id": getattr(c, "PROFILE_ID", None),
        "repeat_threshold": getattr(c, "REPEAT_THRESHOLD", None),
        "layer_evidence_max": getattr(c, "LAYER_EVIDENCE_MAX", None),
        "form5_sentence_max": getattr(c, "FORM5_SENTENCE_MAX", None),
        "signal_table_sha256": getattr(c, "SIGNAL_TABLE_SHA", None),
        "cutover": getattr(c, "DEFAULT_CUTOVER", None),
    }


def judge_round_delegate(reply_text: str, material: str = "", ts: str = None) -> tuple:
    """★ **委派判据**：调可执行底的 `judge_round()`。★ 返 `(findings, meta)` —— meta 里有「判当刻的口径指纹」。"""
    c = load_check()
    try:
        r = c.judge_round(reply_text or "", material=material or "", ts=ts)
    except Exception as e:                                      # noqa: BLE001
        return [{"name": "judge_round", "verdict": "uncomputable",
                 "detail": "判据底抛错：{0}: {1}".format(type(e).__name__, e)}]
    items = r.get("findings") if isinstance(r, dict) else r
    if isinstance(items, dict):
        items = [{"name": k, "verdict": v, "detail": ""} for k, v in items.items()]
    # ★★ 修（v3.7）：**同时回带顶层元数据**（含「判当刻的口径指纹」）。
    #   ★ 原只返 "findings" ⇒ ★ **那个指纹被丢了**，而丢了**不会报错**。
    meta = ({k: v for k, v in r.items() if k != "findings"} if isinstance(r, dict) else {})
    return list(items or []), meta


def map_miss_split(findings: list, evidence: str) -> dict:
    """★★ **把报红拆成两类**：`映射表未覆盖`（表的缺陷）vs `层与依据不符`（执行的错）。

    ★★ 为什么必须拆（实测逼出来的）：
      在本机 v3.5 时代 10 轮上，`layer_vs_evidence` 报红 **7** 条，而
      **7/7 都是"映射表推不出"** —— 真正的"层与依据不符" = **0**。
      ⇒ ★ 那条判据当时**100% 在报假警报**：它在度"表够不够用"，不是"层对不对"。
      ⇒ ★★ 而报告（诊断 v3 建议②）说得对：**假警报多了，真警报就没人看了。**

    ★ 本函数**只做归类读数，不改判据的任何裁决**（裁决权在可执行底，不在这里）。
      它把"表的缺陷"从红项里**显式标出来**，让下游能分开计数。
    """
    c = load_check()
    red = {f.get("name") for f in findings if f.get("verdict") == "red"}
    out = {"map_miss": [], "layer_mismatch": []}
    if "layer_vs_evidence" in red:
        derived = c.layers_from(evidence or "")
        if not derived:
            # 表里一个关键词都没有 ⇒ 这条红是**表的缺陷**，不是执行者的错
            out["map_miss"].append({
                "judge": "layer_vs_evidence",
                "evidence": (evidence or "")[:40],
                "why": "该片段不含映射表任何关键词 ⇒ 层推不出（表未覆盖该表达）",
            })
        else:
            out["layer_mismatch"].append({
                "judge": "layer_vs_evidence",
                "evidence": (evidence or "")[:40],
                "derived": sorted(derived),
                "why": "表能推出层，但写的层超出它 ⇒ 这才是执行的错",
            })
    out["map_miss_n"] = len(out["map_miss"])
    out["layer_mismatch_n"] = len(out["layer_mismatch"])
    out["note"] = ("★ `map_miss` 是**判据表自己的缺陷**，与'判据报红'分开计数；"
                   "★ 本件只归类，**不改判**（判据裁决权在 `checks\\落款校验.py`）")
    return out



def material_fingerprint(msg: str) -> dict:
    """★ `材料指纹`：**只落 长度 + 首 20 字 + 其 sha256** —— ★ **不落原文**（§13.2 硬规）。

    ⚠️ 本函数曾被一次插入编辑**误删 `def` 行**（只剩函数体）⇒ 自测报 `NameError: MSG`。
      ★ 记这一条：**改文件后立刻跑自测**是唯一能当场抓住这种"删掉了却没报语法错"的手段。
    """
    m = msg or ""
    head = m.strip()[:20]
    # ★★ B-30（v3.7 落 · 决定单 D-1.1 / D-1.2 按默认）：多存**归一化全文哈希 + 前 200 字**。
    #   为什么：" + BT + "落款校验" + BT + " 的 " + BT + "layer_evidence_verbatim" + BT + " 判的是「层依据是**材料**的逐字子串」
    #   ⇒ ★ 材料不在场就**不可复判**（" + BT + "uncomputable" + BT + "）。★ 而只存 " + BT + "length/head20/sha256" + BT + " 时，
    #   复判只能去 " + BT + "sessions.json" + BT + " 取原文 —— ★ 而那本**会被界面删改**。
    #   ★ 实测（220 轮）：前 200 字 ⇒ **材料全在段内 96.4%** · **层依据片段在段内 98.8%**
    #     （片段出处中位 = 第 0 字）⇒ ★ 残余 1.2–3.6% 就该是 " + BT + "uncomputable" + BT + "（不可核 ≠ 通过）。
    #   ★ 隐私：乙档的代价**有界**（每轮 ≤200 字）。
    #   ★ 旧轮（无此两项）：**不补**，标「前 B-30 纪元」（D-1.4）。
    _norm = " ".join(m.split())
    return {
        "length": len(m),
        "head20": head,
        "sha256": hashlib.sha256(m.encode("utf-8")).hexdigest(),
        # ★★ 两个哈希，**语义不同，不可互换**：
        #   · `sha256`（★ **既有字段，不改名**）= **原文全文**的哈希
        #     ⇒ ★ 它是 `rebuild()` 找回原文的**契约**（重建文档逐字引用 `材料指纹.sha256`）
        #     ⇒ ★ 且它与 `head200`（原文前 200 字）**同源** ⇒ **可自校验**。
        #   · `norm_sha256` = **归一化全文**（折叠空白）的哈希 ⇒ 用于"同一材料换了排版"的判定
        #     ⇒ ★ **不用它校 `head200`**（一个归一化、一个不归一化，**对不上**）。
        #   ★ A 初版两次错：① **只用 `norm_sha256` 去校 `head200`**（对不上）；
        #     ② **另加一个 `raw_sha256`** —— ★ 它与既有 `sha256` **同值** ⇒ 实测发现后删掉
        #     （★ 本体系"最小字段集"精神：**同值不立第二个名**）。
        "norm_sha256": hashlib.sha256(_norm.encode("utf-8")).hexdigest(),
        "head200": m[:_B30_HEAD_N],
        "b30": True,
    }


#: 十四位的**四族**前缀（M 明 · T 时 · A 事 · S 己）
#   ⚠️ 首版这里写成了 `[MTA]` —— **漏了 S 族** ⇒ 实测 `…A1 A3 S1（层：…` 里的 `S1` 取不到，
#      而它会静默少算一位（位集偏小 ⇒ 形态/事件判断跟着错）。
#   ⇒ 抽成常量，并在自测里断言"四族都能取到"。
#: ★ B-30 决定单 D-1.2：材料保留前 N 字（实测拐点：200）
_B30_HEAD_N = 200

POS_PREFIX = "MTAS"
POS_RE = re.compile(r"([" + POS_PREFIX + r"]\d)")


def parse_positions(text: str) -> list:
    """十四位的位集。★ 这一项**不属于 §13.4**（可执行底不管它）⇒ 仍由本件解析。

    ⚠️ 两条踩过的坑（留着，因为会复发）：
      ① 字符类**不能漏 S 族**（首版写 `[MTA]` ⇒ `S1` 静默取不到 ⇒ 位集少一位、
         形态与事件判断跟着错）；
      ② 不要用 `\\b`（它在中文与字母之间不成立 ⇒ 紧挨中文的那个位会漏）。
    """
    m = re.search(r"思考位[：:]\s*([^\n]*)", text or "")
    if not m:
        return []
    seen, out = set(), []
    for p in POS_RE.findall(m.group(1)):
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _find_positions(text: str) -> tuple:
    """取 `思考位：…` 那一串里的十四位符号。返回 (位集, 原始片断)。"""
    m = re.search(r"思考位[：:]\s*([^\n]*)", text)
    if not m:
        return [], ""
    raw = m.group(1)
    # 十四位形如 M1 M4 T1 A3 S1；按出现顺序取全
    # ⚠️ 也不要用 `\b` —— 它在中文字符与字母之间不成立
    #    （实测：`…A3 S1（层：…` 里紧挨中文的那个位会漏）。
    pos = POS_RE.findall(raw)
    seen, out = set(), []
    for p in pos:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out, raw.strip()


def footer_region(text: str) -> str:
    """★ **只取落款区**（`思考位` … 到正文结束/下一个空行块）。

    ⚠️⚠️ 这一步是**必须的**，而首版**漏了它** ⇒ 实测抓到一个真 bug：
      我在**整篇正文**里搜 `层[：:]`，而正文里会有 `**持久层**：没有` / `层：没有。**` 这种句子
      ⇒ 于是把**正文的垃圾串**当成了 `层` 字段（实测落进账的值是
      `'没有。** 我这一轮没有可写的会话侧存储…按 §13.2：'`），**而且它没进 `undeclared`**
      ⇒ ★ **账里存了假值** —— 正好违反本件自己写的"不许静默留空"。

    ★ 故：**先切出落款区，再在落款区里取字段**。取不到 ⇒ `undeclared`（显式），不猜。
    """
    t = text or ""
    m = re.search(r"思考位[：:]", t)
    if not m:
        return ""
    # 落款从 `思考位：` 起，到文末；但**斩在下一个"看起来像新标题"的空行块**之前
    seg = t[m.start():]
    # 落款最多几十行；遇连续两个空行（\n\n\n）或超长即止
    cut = re.search(r"\n\s*\n\s*\n", seg)
    if cut:
        seg = seg[:cut.start()]
    return seg[:1200]


def _find_field(text: str, *names: str) -> str:
    """在**落款区**里取字段。

    ⚠️ 两条都踩过：
      ① **必须限定在落款区里搜**（见 `footer_region`）—— 否则抓到正文里的同名字样。
      ② ★★ **`层` 不能被「层依据：」抢先匹配**：真实落款形如
         `（层依据：「…」 · 层:事* · 位来源：层选 · …）`
         ⇒ 用 `层[：:]` 会**先命中「层依据：」**，取到 `依据` 那一串。
         ⇒ 故加**负向先行** `(?!依据)`，让它只认独立的 `层:`。
    """
    for n in names:
        m = re.search(n + r"(?!依据)[：:]\s*([^·）)\n|]*)", text)
        if m:
            return m.group(1).strip()
    return ""


#: `层` 的**合法取值**（§13 四层 + 认不出的两档）
LAYER_OK = ("明", "时", "事", "己", "层判不明", "未命中四层信号", "不适用", "无")


def _clean_layer(v: str) -> str:
    """★ 值域检查：`层` 只该是四层名或那几档，**允许尾随标记星号**。

    ⚠️ 为什么要有它：即使切了落款区，**万一落款本身写得古怪**，也不该把长串正文塞进账。
      超长 / 不认得的 ⇒ **返回空**（由调用方落进 `undeclared`），★ **不许存进账**。

    ⚠️⚠️ 而它**必须两向都对**（首版只对一向 ⇒ 实测**误杀**）：
      · 挡垃圾 ✔   · ★ **但也不能把合法值挡掉** —— 实测 `事*`（四层名+标记星号）被首版判空
        ⇒ 那会让"该有的层"变成 `None`，账**反向失真**。
      ⇒ 故：先剥尾随标记符 `*＊`，再判。
    """
    s = (v or "").strip().strip("：: ").rstrip("*＊").strip()
    if not s or len(s) > 12:
        return ""
    if s in LAYER_OK:
        return s
    if "判不明" in s:
        return "层判不明"
    # 允许"明+事"这类组合（都是单字层名）
    if re.fullmatch(r"[明时事己]{1,4}([+＋、][明时事己]{1,4})*", s):
        return s
    return ""


def parse_footer(text: str) -> dict:
    """解析落款。★★ **首选委派**给正本指定的可执行底；底不在才退回本件的正则。

    ★ 为什么以委派为先：§13.4 明写那份脚本是**可执行底**，且正本 §0「与代码冲突时以代码为准」
      ⇒ **判据的解释权在它那里**，本件不该另有一套（实测缺口：它取 12 个键、我不取其中 11 个）。
    ★ 退回分支**保留**是为了"本项目被单独拷走时仍能落账"，但会**显式标 `delegated=False`**
      ⇒ 读数里能看出"这一轮的解析不是权威那份给的"。
    """
    t = text or ""
    try:
        check = load_check()
        sig = check.parse_signature(t)
        delegated = True
    except Exception:                                           # noqa: BLE001
        check, sig, delegated = None, None, False

    if delegated and sig is not None:
        positions = parse_positions(t)
        layer = _clean_layer(sig.get("layer") or "")
        ev = sig.get("evidence")
        source = sig.get("source")
        form = sig.get("form")
        has_ev_field = bool(sig.get("has_evidence_field"))
        f5q = sig.get("f5_quad") or {}
        f5s = sig.get("f5_sentence")
        m4 = None
        mm = re.search(r"M4\s*反方条件\s*[：:]\s*([^·）)\n|]*)", t)
        if mm:
            m4 = mm.group(1).strip() or None
        unclear = bool(layer and "判不明" in layer)
        praw = sig.get("layer")
        return {
            "位集": positions,
            "位来源": (source or None),
            "层": (layer or None),
            "是否层判不明": unclear,
            "M4 反方条件": m4,
            # ---- v3.5 §13.4 新增席位（★ 从可执行底原样取）----
            "层依据": (ev or None),
            "层依据带引号": bool(sig.get("evidence_quoted")),
            "有无层依据栏": has_ev_field,
            "f5_sentence": f5s,
            "f5_present": bool(sig.get("f5_present")),
            "f5_quad": f5q,
            # ---- 元信息 ----
            "落款形态": form,
            "落款形态说明": FORM_NAMES.get(form, "（认不出 ⇒ undeclared）") if form else "（无落款）",
            # ★★ `位集档` = **本件自己的**轴（"没走位"是数据）；
            #    ★ 明确**不冒充** §13.4 的 `落款形态`（底把 1/2/3 归并、且不细判 4 vs 1）
            "位集档": ("空位集" if not positions else "走位"),
            "是否带落款": bool(sig.get("has_sig")),
            "delegated": True,
            "delegated_to": str(next((p for p in CHECK_PATHS if p.exists()), "")),
            "_原始片断": praw,
            "undeclared": [k for k, v in (
                ("位来源", source), ("M4 反方条件", m4),
                ("层", layer if not ev else "（v3.5：有层依据，层可省）"),
            ) if not v],
            "层缺失性质": (None if layer else
                          ("v3.5-有层依据-层可省（合法）" if ev else
                           ("判据晚于账（v3.5 前无此栏）" if not has_ev_field else "真未给"))),
        }

    # ---------------- 退回：本件自己的正则（★ 会标 delegated=False） ----------------
    region = footer_region(t)
    scope = region or t
    positions, praw = _find_positions(scope)
    source = _find_field(scope, "位来源")
    layer = _clean_layer(_find_field(scope, "层"))      # ★ 值域检查
    layer_basis = _find_field(scope, "层依据")          # ★ v3.5：只报依据、`层` 可省
    selfcheck = _find_field(scope, "自检")
    m4 = _find_field(scope, "M4 反方条件", "M4反方条件", "反方条件")

    has_footer = bool(re.search(r"思考位[：:]", t)) or bool(
        re.search(r"显化声明[：:]", t))

    # ★ 落款形态：4/5 是"位集为空"的两档 —— **"没走位"本身是数据**
    #   ⚠️ 次序要紧：**先判 5（不适用）再判 4（最小入口）** ——
    #      否则"不适用但写了思考位：空"那种会被归成 4（两档意思不同，不许合并）。
    not_applicable = bool(re.search(r"不适用|不落入本模型|本问题不适用", t))
    if not has_footer:
        form = 5 if not_applicable else None
    elif not positions:
        form = 5 if not_applicable else 4
    elif "触发" in selfcheck and "未触发" not in selfcheck:
        form = 2
    elif re.search(r"护根", t):
        form = 3
    else:
        form = 1

    unclear = ("判不明" in layer) or ("判不明" in t and not layer)

    return {
        "位集": positions,
        "位来源": source or None,
        "层": layer or None,
        "是否层判不明": bool(unclear),
        "M4 反方条件": m4 or None,
        "层依据": layer_basis or None,     # ★ v3.5 新增：`层` 可省、依据要有
        "层依据带引号": None,
        "有无层依据栏": bool(layer_basis),
        "f5_sentence": None,
        "f5_present": False,
        "f5_quad": {},
        "是否带落款": has_footer,
        "delegated": False,
        "delegated_to": None,
        "落款形态": form,
        "落款形态说明": FORM_NAMES.get(form, "（认不出 ⇒ undeclared）") if form else "（无落款）",
        "位集档": ("空位集" if not positions else "走位"),
        "_原始片断": praw,
        # ★ 提不出的项，显式列出来（下游要能看见"哪几项缺"）
        #   ⚠️ 附**为什么缺**：`层` 缺有两种，意思完全不同，不许混成一句 ——
        #     · 有 `层依据` ⇒ ★ **v3.5 的合法形态**（正本：只报输入、不报结论，`层` 可省）⇒ **不算缺**
        #     · 无 `层依据` ⇒ 真的没给
        "undeclared": [k for k, v in (
            ("位来源", source), ("M4 反方条件", m4),
            ("层", layer if not layer_basis else "（v3.5：有层依据，层可省）"),
        ) if not v],
        "层缺失性质": (None if layer else
                      ("v3.5-有层依据-层可省（合法）" if layer_basis else "真未给")),
    }


# ---------------------------------------------------------------------------
# 二、事件标注（**持有方裁定**：**不单独开账**，写进同一轮记录）
# ---------------------------------------------------------------------------

def annotate_events(detail: dict) -> dict:
    """把**能机械判定**的事件标出来；判不出的**不写**（不猜）。

    ★ 本件**只标它真能证的**：
        · 补位 —— 位集里含 `M4`/`A3`（§5.2 第二步：强制补这两个位）
        · 裁剪 —— 位数 > 6（§5.2 `MAX_POS=6` ⇒ 必然经过裁剪）
        · 自检触发 —— 落款自检栏写的是"触发"
        · 降级 —— 落款/正文出现降级字样
        · 错位 —— ★ **机械判不出**（要对照层→位的规则）⇒ **不标**，留给能判的一方
    """
    pos = detail.get("位集") or []
    ev: dict = {}
    if any(p in ("M4", "A3") for p in pos):
        ev["补位"] = "位集含 M4/A3（§5.2 第二步强制补位）"
    if len(pos) > 6:
        ev["裁剪"] = "位数 {0} > MAX_POS=6".format(len(pos))
    sc = str(detail.get("_自检原文") or "")
    if "触发" in sc and "未触发" not in sc:
        ev["自检触发"] = sc or "落款自检栏=触发"
    if re.search(r"降级", str(detail.get("_正文") or "")):
        ev["降级"] = "正文出现降级字样"
    return ev


# ---------------------------------------------------------------------------
# 三、落账（append-only）
# ---------------------------------------------------------------------------

#: ★★ B-43：会话侧链的伴生文件（D-2.1：**各自一条链**）。
CHAIN = HIST / "session_log.chain.jsonl"
#: ★ 哨兵：**必须定义在用它的函数之前**（★ A 初版放在后面 ⇒ 首调 NameError 被 try 吞）。
_UNSET = object()
_TC_CACHE = _UNSET

#: ★ B-43：偏好用绝对路径做 "verification_path"（★ 因为 node 侧 "verifyChain" 会**去磁盘验它存不存在**）。
_NODE_CACHE = {}


def _node_block() -> dict:
    """★ 从 "node_declaration.json" 取本节点声明（★ 取不到就**报**，不编）。"""
    f = HIST / "node_declaration.json"
    mtime = f.stat().st_mtime if f.exists() else 0
    if _NODE_CACHE.get("mtime") == mtime and _NODE_CACHE.get("v"):
        return _NODE_CACHE["v"]
    # ★★ 修（A 自查）："CRITERIA_FILE" 是 **direction_history.py 的常量**，本文件**没有**
    #   ⇒ 初版直接引用 ⇒ NameError。★ 改为**只用本文件真有的**：声明里的 return_path，否则 APP 下的 README。
    node_id, rp = "rootthink-studio", str(APP / "README.md")
    if f.exists():
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
            node_id = j.get("node_id") or node_id
            rp = j.get("return_path") or rp
        except Exception:                                       # noqa: BLE001
            pass
    v = {"node_id": node_id, "is_manifestation": True, "verification_path": str(rp)}
    _NODE_CACHE.update({"mtime": mtime, "v": v})
    return v


def append_chain(rec: dict, log: pathlib.Path = LOG) -> dict:
    """★★★ B-43 接线：把**刚写的那一行账**同步写进会话侧链。

    ★ 三条硬约束（规格 §3.1）：
      ① **写链失败绝不许弄坏主作业**（与本件现有的"记账失败只吞异常"同法），
        ★ **但必须打印出来**（不许静默）；
      ② **口径指纹用 "judge" 当刻那个**（"criteria_hash_runtime" · 不用记账当刻重算）；
      ③ 链文件与账本**同目录**。
    """
    try:
        # ★★ 统一命名（A 实测踩坑）：★ 四本账一律 "<账文件名>.chain.jsonl"
        #   ⇒ ★ **"chain_status" 与 "trace_chain --backfill" 都按这个路径找**；
        #     ★ A 初版写成固定的 "session_log.chain.jsonl" ⇒ **生成了两个链文件**。
        tf = pathlib.Path(str(log) + ".chain.jsonl")
        tc = _trace_chain()
        if tc is None:
            return {"ok": False, "why": "trace_chain 不可用（已告警）"}
        cm = rec.get("check_meta") or {}
        # ★★ 两套参数，**必须分四个名字**（★ A 实测踩坑）：
        #   · **痕迹规范要的那套**（"min_suspect_len / low / high" · 属检测页阈值）
        #     ★ **落款校验里真的没有** ⇒ ★ 不能伪造，故置 None 并**标明原因**；
        #   · **落款校验自己的那套**（"repeat_threshold / layer_evidence_max / form5_sentence_max）
        #     ★ **它才是本账真正的口径** ⇒ ★ 必须入链，否则 B-13 等于没关。
        crit = {
            "prompt_version": "v3.7",
            "model_id": str(cm.get("profile_id") or "nfkc@v1"),
            "criteria_hash": rec.get("criteria_hash_runtime"),
            "criteria_source": (_node_block() or {}).get("node_id"),
            "calibrated": False,
            "calibration_id": None,
            "_trace_spec_required": {"min_suspect_len": None, "low": None, "high": None},
            "_trace_spec_note": "★ 痕迹规范 §3.1 那三项属**检测页**阈值，落款校验里**不存在** ⇒ 置 None（不伪造）。",
            "check_src": cm.get("check_src"),
            "profile_id": cm.get("profile_id"),
            "repeat_threshold": cm.get("repeat_threshold"),
            "layer_evidence_max": cm.get("layer_evidence_max"),
            "form5_sentence_max": cm.get("form5_sentence_max"),
            "signal_table_sha256": cm.get("signal_table_sha256"),
            "cutover": cm.get("cutover"),
        }
        return tc.append_trace(tf, {
            "node": _node_block(),
            "kind": "trace",
            "criteria": crit,
            "state": {"phase": "running", "frozen": False,
                      "requires_human": bool(rec.get("red"))},
            "action": {"type": "observe", "trigger": "none",
                       "trigger_detail": "会话侧每轮记账（B-43 接线）"},
            "evidence": {"session": rec.get("session"), "turn_no": rec.get("turn_no"),
                         "ts": rec.get("ts"),
                         "red": rec.get("red"), "green": rec.get("green"),
                         "uncomputable": rec.get("uncomputable"),
                         "落款形态": rec.get("落款形态")},
        })
    except Exception as e:                                      # noqa: BLE001
        return {"ok": False, "why": "{0}: {1}".format(type(e).__name__, str(e)[:80])}


def _trace_chain():
    """★ 本外发版：★ **本包不含"协作链"这一件** ⇒ ★ 这里**直接返回 None**（★ 不做任何路径探测）。

    ★ 为什么不做探测：★ 那一件**从来不在本包里** ⇒ ★ 探测没有意义，
      ★ 而**探测用的那几个候选路径**会把"更完整版本"的目录结构带进外发包
      ⇒ ★ 那属**本地信息**，★ 一律不留。
    ★ 行为与"探测失败"**完全一样**（调用方拿到 None）⇒ ★ 不改动任何既有逻辑。
    """
    global _TC_CACHE
    if _TC_CACHE is not _UNSET:
        return _TC_CACHE
    _TC_CACHE = None
    return None



def record(session_id: str, user_text: str, reply_text: str,
           mode: str = "", protector: bool = False, turn_no: int | None = None,
           log: pathlib.Path = LOG,
           形状: str | None = None,
           乱: dict | None = None,
           乱纪律: list | None = None) -> dict:
    """★ 服务端每轮调它。写**一条**：七项 + 事件标注 + 材料指纹（**不含原文**）。"""
    det = parse_footer(reply_text)
    det["_自检原文"] = _find_field(reply_text or "", "自检")
    det["_正文"] = reply_text or ""
    det["events"] = annotate_events(det)
    # 内部辅助字段不落盘
    for k in ("_正文", "_sig"):
        det.pop(k, None)
    det.pop("_自检原文", None)

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    # ★★ §13.4 八条判据的**读数**（委派给正本指定的可执行底；原样取，不改判）
    findings, _judge_meta = judge_round_delegate(reply_text or "", material=user_text or "", ts=ts)
    # ★★ **两个指纹，语义不同，不可互代**（实测：两者值必然不同）：
    #   · `criteria_hash_runtime`（★ **主**）= **判当刻底实用的口径常量集**（由 `judge_round` 自己返回）
    #     ⇒ ★ 它回答「**这一轮到底被哪版口径判过**」 —— ★ 避开了"记账当刻 vs 判当刻"的错位。
    #   · `criteria_hash_canonical`（次）= **判据表的结构指纹**（判据名 + 状态 + 被谁取代 + 后果）
    #     ⇒ ★ 它回答「**当时正本长什么样**」。★ 两者合起来才是 B-13 真正关掉。
    # ★ 指纹在**顶层**（★ 实测：底的 "judge_round" 把它放在顶层，而 "delegate" 原只取 findings ⇒ 丢了）
    _ch_rt = _judge_meta.get("criteria_hash") if isinstance(_judge_meta, dict) else None
    _ch = None
    try:
        import check_criteria as _cc
        _ch = _cc.criteria_hash()
    except Exception:                                       # noqa: BLE001
        _ch = None
    rec = {
        "ts": ts,
        "criteria_hash_runtime": _ch_rt,
        # ★★★ B-30/不算输出（v3.7 接 · 2026-10-08）：**整轮定性**
        #   ★ 它由**底**在判当刻算出（契约字段 "not_output" / "not_output_why"）
        #     ★ 故本处只**原样转写**，不重算（★ 重算就是第二份定义）。
        #   ★ 取不到 ⇒ None（★ 不编"False" —— ★ 那会把"不知道"洗成"算输出"）。
        "not_output": (_judge_meta or {}).get("not_output"),
        "not_output_why": (_judge_meta or {}).get("not_output_why") or "",
        "criteria_hash_canonical": _ch,
        "session": session_id,
        "turn_no": turn_no,
        "mode": mode,
        "protector": bool(protector),
        "材料指纹": material_fingerprint(user_text),      # ★ 只指纹，不原文
        # ---- §13.2 原七项 ----
        "位集": det["位集"],
        "位来源": det["位来源"],
        "层": det["层"],
        "是否层判不明": det["是否层判不明"],
        "M4 反方条件": det["M4 反方条件"],
        "落款形态": det["落款形态"],
        "落款形态说明": det["落款形态说明"],
        # ---- ★ v3.5 §13.4 新增席位（对齐可执行底，2026-10-06 优化）----
        "层依据": det.get("层依据"),
        "层依据带引号": det.get("层依据带引号"),
        "有无层依据栏": det.get("有无层依据栏"),
        "层缺失性质": det.get("层缺失性质"),
        "f5_sentence": det.get("f5_sentence"),
        "f5_present": det.get("f5_present"),
        "f5_quad": det.get("f5_quad"),
        "是否带落款": det.get("是否带落款"),
        "位集档": det.get("位集档"),          # ★ 本件自己的轴（空位集/走位），不冒充 §13.4 形态
        # ---- ★★ 判据读数（§13.4 八条）—— 从此判据**直接建在会话侧账上** ----
        "judgements": {f.get("name"): f.get("verdict") for f in findings},
        "judgement_detail": [{"name": f.get("name"), "verdict": f.get("verdict"),
                              "detail": (f.get("detail") or "")[:160]} for f in findings],
        "red": sorted({f.get("name") for f in findings if f.get("verdict") == "red"}),
        "green": sorted({f.get("name") for f in findings if f.get("verdict") == "green"}),
        "uncomputable": sorted({f.get("name") for f in findings
                                if f.get("verdict") == "uncomputable"}),
        # ★★ 「表的缺陷」与「执行的错」**分开计数**（报告建议②；实测 7/7 是前者）
        "map_split": map_miss_split(findings, det.get("层依据") or ""),
        # ---- 解析来源（★ 能看出这一轮是不是权威那份给的）----
        "delegated": det.get("delegated"),
        "delegated_to": det.get("delegated_to"),
        # ---- 口径回显（判据底自己的，不自己编）----
        "check_meta": check_meta(),
        "undeclared": det["undeclared"],                  # ★ 提不出的项，显式
        "events": det["events"],                          # ★ 事件=标注，不单独开账
        "reply_sha256": hashlib.sha256((reply_text or "").encode("utf-8")).hexdigest(),
    }
    # ★★★★★ 2026-10-13 加：★ **读数区**（★ A/C 两组靠它 · ★ 见生成脚本 ⑤a-6）
    #   · `形状`   —— 本轮输出的形状（★ 治"合规的重复"）
    #   · `乱`     —— **本轮输入侧的读数**（★ 证据）
    #   · `乱纪律` —— **本轮注入过什么**（★ 动作 · ★ 空表 = 没注入）
    #   ★★ 为什么两个都落：★ **C 组的对照靠它** ——
    #     有 `乱纪律` 的轮 =「有动作」· 无的轮 =「没动作」⇒ ★ 两类同账积累、可对读。
    #   ★★★ 而**只在真有时才写那两个键**（★ 读数为空时**不写**）——
    #     这样 `r.get("乱") is not None` 才能把"没算"与"算了是 0"分开（★ 两者意义不同）。
    if 形状:
        rec["形状"] = 形状
    if 乱 is not None:
        rec["乱"] = 乱
        rec["乱纪律"] = list(乱纪律 or [])
    log.parent.mkdir(parents=True, exist_ok=True)
    # [atomic-append] ★ B-35：改用持锁原子追加（原为裸 open("a").write）
    atomic_io.append_line(log, rec)
    # ★★★ 本外发版：★ **不写协作链** —— ★ 这一件（"协作链"读写器）
    #   ★ **本来就不在本包里**（★ 本版是"帮人看清问题"的单机工具，没有协作层）。
    #   ★ 故原版这一句与它下面那两行**已删**：★ 每轮报一次"写链未成"，
    #     ★★ 反而会让使用者以为**包里坏了什么**（★ 而**账是照写的、一行没少**）。
    #   ★★ 这条不是"静默降级"：★ 账（`history\session_log.jsonl`）是**完整**的 ——
    #     ★ 缺的只是"协作链"这一层，★ 而它**从来没有出现在本包里**。
    return rec


#: ★★ B-30 的乙档生效时刻（★ 用于给旧行标「前 B-30 纪元」）
B30_ERA_FROM = "2026-10-08 10:04:00"


def material_era(rec: dict) -> str:
    """★★ D-1.4：**判一行账属于哪个材料纪元**（★ **只读，不改账**）。

    ★ 为什么要有它：★ 乙档（B-30）之前的行，`材料指纹` 里**没有材料本体**（只有 `length/head20/sha256`）
      ⇒ ★ 那些行的 `layer_evidence_verbatim` **无法单凭账重判**（得去 `sessions.json` 取原文，★ 而那本**会被删改**）。
    ★ 当年不标，就会有人把它读成「**这一轮没有材料**」—— ★ 而实际是「**这一轮在乙档之前，本就不存**」。
      ★ 这正是墓碑机制要治的「**陈旧无记号**」。

    ★ 返回：`"乙档"` / `"前 B-30 纪元"` / `"无材料档"`。
    """
    mf = rec.get("材料指纹")
    if mf is None:
        return "无材料档"
    if mf.get("b30"):
        return "乙档"
    return "前 B-30 纪元"


def not_output_census(log: pathlib.Path = LOG) -> dict:
    """★ 「该轮不算本模型的输出」的计数（★ 只读）。

    ★ 为何**单独计**：★ 它不是一条红，而是**整轮定性** ⇒
      ★ **不混进红项合计**（★ 避它被当成“又一条红”而麻木）。
    ★ ★ **三档**：`True`（不算输出）/ `False`（算）/ `None`（★ 旧轮 · 本栏当时不存在）。
    """
    out = {"不算输出": 0, "算输出": 0, "未标注（★ 旧轮）": 0, "total": 0}
    if not log.exists():
        return out
    for ln in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if not ln.strip():
            continue
        try:
            r = json.loads(ln)
        except Exception:                                       # noqa: BLE001
            continue
        out["total"] += 1
        v = r.get("not_output")
        if v is True:
            out["不算输出"] += 1
        elif v is False:
            out["算输出"] += 1
        else:
            out["未标注（★ 旧轮）"] += 1
    return out


def era_census(log: pathlib.Path = LOG) -> dict:
    """★ 四档的**行数盘点**（★ 只读）。"""
    out = {"乙档": 0, "前 B-30 纪元": 0, "无材料档": 0, "total": 0, "说明": ""}
    if not log.exists():
        return out
    for ln in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if not ln.strip():
            continue
        try:
            r = json.loads(ln)
        except Exception:                                       # noqa: BLE001
            continue
        out[material_era(r)] = out.get(material_era(r), 0) + 1
        out["total"] += 1
    old = out["前 B-30 纪元"] + out["无材料档"]
    if old:
        out["说明"] = ("★ **{0} 行属「前 B-30 纪元」** —— "
                              "★ 它们的材料本体**不在行里**，"
                              "故 `layer_evidence_verbatim` **无法单凭账重判**"
                              "（★ 需 `sessions.json`，而那本**会被删改**）。"
                              "★ **不是「这一轮没有材料」**。").format(old)
    return out


def chain_status(log: pathlib.Path = LOG) -> dict:
    """★★ 步 2（B-43）：**链对账** —— 链条数 vs 账行数 + 链自校。

    ★ 为何必须有它：★ **链只能证明「链上的记录未被改」，
      不能证明「账里没别的行」** —— ★ 若某个写点绕过 Python，它就不在链上。
      ★ 故**两个数不等就要报**。
    """
    out = {"ledger": str(log), "rows": None, "chain": None, "ok": False, "why": ""}
    try:
        out["rows"] = len([x for x in log.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]) if log.exists() else 0
    except OSError as e:
        out["why"] = "账不可读：{0}".format(e)
        return out
    chf = pathlib.Path(str(log) + ".chain.jsonl")
    if not chf.exists():
        out["why"] = "尚无链（新盘/未接）"
        out["ok"] = out["rows"] == 0
        return out
    tc = _trace_chain()
    if tc is None:
        out["why"] = "trace_chain 不可用"
        return out
    st = tc.read_chain(chf)
    out["chain"] = len(st["records"])
    if not st["ok"]:
        out["why"] = "链里有坏行：{0}".format(st["bad"][:2])
        return out
    vr = tc.verify_chain(st["records"])
    if not vr["ok"]:
        out["why"] = "链自校失败（断点 seq={0}）".format(vr.get("break_at"))
        out["verify"] = vr
        return out
    if out["chain"] != out["rows"]:
        out["why"] = "★ **条数不符**：链 {0} · 账 {1} ⇒ 有行绕过了写链".format(out["chain"], out["rows"])
        return out
    out["ok"] = True
    out["why"] = "链与账一致（{0} 条）且自校通过".format(out["chain"])
    return out


def backup_ledger(log: pathlib.Path = LOG, why: str = "rewrite") -> str:
    r"""★★ 建议 7（v3.7 加）：**全量重写账之前先备份**。

    为什么：`--rebuild --write` 与 `--cross-round --write` **都是全量重写**，
      ★ 而原实现**没有任何备份动作**（实测：两处都只有一行 `write_text`）
      ⇒ 一次重算就能**静默覆掉原账**。

    ★ 命名跟 `_history\_backups\` 那一套：`<件名>_<why>前_<HHMMSS>.<后缀>`
      ★ **不用旧的 `*_备份` 命名**（那一套无时间戳、无行为名、无到期条件）。
    ★ 返回备份名（或失败说明）—— **不抛**，因为备份失败不应阻断主作业，**但必须报出来**。
    """
    try:
        import shutil as _sh
        d = log.parent / "_backups"
        d.mkdir(parents=True, exist_ok=True)
        base = log.name + "_" + why + "前_" + time.strftime("%H%M%S")
        b = d / (base + log.suffix)
        k = 2
        while b.exists():
            b = d / (base + "-" + str(k) + log.suffix)
            k += 1
        _sh.copyfile(log, b)
        return b.name
    except Exception as e:                                      # noqa: BLE001
        return "备份失败：{0}".format(str(e)[:60])


def _rows(log: pathlib.Path = LOG) -> list:
    if not log.exists():
        return []
    out = []
    for ln in log.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if ln:
            try:
                out.append(json.loads(ln))
            except Exception:                                   # noqa: BLE001
                continue
    return out


def probe() -> dict:
    """★ 探针：**证明这个持久层能写、能读回**（不删历史）。

    为什么要有它：§13.2 要求"探针跑没跑过"必须如实标 ——
    而**不许合并**这两句：`会话侧：无持久层（探针已跑）` / `装机前提：未执行`。
    ⇒ 故本函数**真去写一条探针记录、读回来、再删掉探针文件**，用读数说话。
    """
    if PROBE.exists():
        PROBE.unlink()
    ok_write = ok_read = False
    err = ""
    try:
        # [atomic-append] ★ B-35：探针文件也用同一套原子追加（口径一致）
        atomic_io.append_line(PROBE, {"probe": True, "ts": time.time()})
        ok_write = PROBE.exists() and PROBE.stat().st_size > 0
        got = _rows(PROBE)
        ok_read = len(got) == 1 and got[0].get("probe") is True
    except Exception as e:                                      # noqa: BLE001
        err = "{0}: {1}".format(type(e).__name__, e)
    finally:
        try:
            if PROBE.exists():
                PROBE.unlink()
        except Exception:                                       # noqa: BLE001
            pass
    can = ok_write and ok_read
    return {
        "can_write": ok_write,
        "can_read_back": ok_read,
        "probe_file_removed": not PROBE.exists(),
        "error": err,
        "conclusion": ("持久层**可用**（探针已跑：写→读回→删）" if can
                       else "★ 持久层**不可用** ⇒ 按 §13.2 应标 `会话侧：无持久层（探针已跑）`"),
    }


def recompute_cross_round(log: pathlib.Path = LOG, dry: bool = True) -> dict:
    """★★ **重算跨轮判据**（`same_layer_evidence_repeat`）—— 单轮路算不出来的那一条。

    ★★ 为什么必须单独做（实测缺口）：
      `same_layer_evidence_repeat` 的定义是"**同一 `层依据` 片段跨轮反复出现≥阈值**"
      ⇒ 它是**跨轮**判据，**单轮 `judge_round()` 算不出来**，只有 `judge_batch()` 能。
      而 `record()` 是**每轮一次**的即时落账 ⇒ ★ 那条判据在过去 **43 轮里 0 红 0 绿、从未被判**。

    ★ 做法：用 `session_log` 自己当语料（`档位=判据能直接建在会话侧账上`），
      从账里取每轮的 `层依据` + `ts`，调底的 `judge_batch()` 拿**唯一正确的跨轮读数**，
      再把它回填到相关轮的 `judgements` / `red` / `green` / `uncomputable`。

    ⚠️ 只回填**跨轮那一条**；单轮几条**不动**（它们由 `record()` 即时落，且已逐格验过一致）。
    """
    c = load_check()
    rows = _rows(log)
    if not rows:
        return {"error": "账是空的"}
    rounds = [{"text": r.get("_reply") or "", "ts": r.get("ts")} for r in rows]
    # 账里没存回答原文（★ 有意：不落原文）⇒ 用 `层依据` 重建一个"最小可判文本"给跨轮判据用。
    # ★ 这不是绕过判据：`same_layer_evidence_repeat` 只看 `层依据` 的归一化片段，不看别的。
    for i, r in enumerate(rows):
        ev = r.get("层依据")
        rounds[i]["text"] = ("思考位：（层依据：「{0}」 · 位来源：{1} · 自检：未触发）\n"
                             "显化声明：本回答是显化，不是根。".format(
                                 ev or "", r.get("位来源") or "层选"))
        rounds[i]["material"] = ""
    b = c.judge_batch(rounds)
    got = []
    for r, res in zip(rows, b.get("rounds", [])):
        v = None
        for f in (res.get("findings") or []):
            if f.get("name") == "same_layer_evidence_repeat":
                v = f.get("verdict")
        got.append(v)
    from collections import Counter
    tally = Counter(got)
    changed = []
    if not dry:
        out = []
        for r, v in zip(rows, got):
            nr = dict(r)
            if v is not None:
                j = dict(nr.get("judgements") or {})
                if j.get("same_layer_evidence_repeat") != v:
                    changed.append({"ts": nr.get("ts"), "was": j.get("same_layer_evidence_repeat"),
                                    "now": v})
                j["same_layer_evidence_repeat"] = v
                nr["judgements"] = j
                buckets = {"red": "red", "green": "green", "uncomputable": "uncomputable"}
                for nm, key in buckets.items():
                    s = set(nr.get(key) or [])
                    if v == nm:
                        s.add("same_layer_evidence_repeat")
                    else:
                        s.discard("same_layer_evidence_repeat")
                    nr[key] = sorted(s)
            out.append(nr)
        # ★★ 建议 7（v3.7 加）：`recompute_cross_round` **也是全量重写** ⇒ 写回前先备份。
        #   ★ 原实现在这里**没有任何备份动作**（实测）。★ 命名与 `_history\_backups\` 同一套。
        _bkname = backup_ledger(log, why="recompute")
        log.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out),
                       encoding="utf-8", newline="\n")
    return {
        "log": str(log), "rows": len(rows), "rewritten": not dry,
        "cross_round_verdicts": dict(tally),
        "changed_rounds": len(changed), "changed": changed[:30],
        "note": "★ 只回填跨轮那一条；单轮几条由 record() 即时落、已逐格验过一致",
    }


# [health:BEGIN]
# [pending:BEGIN]
#: 待批账（持有方「先积累再一起改」⇒ 这里攒候选，不逐条改机制层）
PENDING_FILE = APP / "待批·机制层修订候选.md"


# [criterion-status:BEGIN]
def criterion_status_line() -> str:
    """B-40 的一行读数（判据落实状况）。★ 缺件时**明说缺**，不静默跳过。"""
    try:
        import criterion_status as cs
        d = cs.build()
        c, k = d["counts"], d["conflicts"]
        return ("判据落实 | 正本 {0} · 底 {1} · 账 {2} · 并集 {3} | "
                "正本有底无 {4} · 底有正本无 {5} · 从没跑过 {6} · 从未红过 {7} | 硬冲突 {8}").format(
            c["正本"], c["底"], c["账里跑过"], c["并集"],
            len(k["正本有底无"]), len(k["底有正本无"]),
            len(k["从没跑过"]), len(k["从未红过"]),
            "有" if d["hard_conflict"] else "无")
    except Exception as e:                                       # noqa: BLE001
        return "判据落实 | ★ 扫描器不可用：{0}: {1}".format(type(e).__name__, e)

# [criterion-status:END]

def pending_items() -> list:
    """从待批账里**只读**抽出待批条目（`| **B-n** | … |` 那种表行）。

    ★ 只解析表格首列形如 `**B-数字**` 的行 —— 故意做得**很窄**：
      宁可漏抽，也不要把它误当成机制层内容去解读。
    """
    if not PENDING_FILE.exists():
        return []
    out = []
    for ln in PENDING_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        if not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) >= 2 and re.fullmatch(r"\*\*B-\d+\*\*", cells[0]):
            out.append({"id": cells[0].strip("*"), "title": cells[1][:60],
                        "fix_or_extend": cells[3] if len(cells) > 3 else ""})
    return out


def pending_line() -> str:
    """一行报出待批条数（给 `--health` 用）。"""
    it = pending_items()
    if not it:
        return "待批：0 条（或待批账不在：{0}）".format(PENDING_FILE.name)
    return "待批 {0} 条（{1}）—— 按持有方「先积累再一起改」，未动机制层".format(
        len(it), " · ".join(x["id"] for x in it))

# [pending:END]

SESSIONS_JSON = APP / "data" / "sessions.json"


def ledger_completeness() -> dict:
    """★★ 建议 1（v3.7 加）：**漏记计数器** —— 「该有多少轮」 vs 「账里有多少行」。

    为什么要它：实测发现行使史**无声地漏记整场会话**（三个会话整场为 0），
      而它之前**没有任何一处会嗊**；更麻烦的是——**总数碰巧接近**（漏记与多记相抵）
      ⇒ 故本条**两个方向都报**（漏记 / 多记），**不只报差值**——否则两种病会互相遮盖。

    ★ 读不到 `sessions.json` 就**不报**（不静默当成“完整”）。
    """
    log_rows = _rows()
    by_log = {}
    for r in log_rows:
        k = r.get("session")
        by_log[k] = by_log.get(k, 0) + 1
    if not SESSIONS_JSON.exists():
        return {"ok": False, "why": "找不到 {0}".format(SESSIONS_JSON.name)}
    try:
        ss = json.loads(SESSIONS_JSON.read_text(encoding="utf-8"))
    except Exception as e:                                      # noqa: BLE001
        return {"ok": False, "why": "读不了：{0}".format(str(e)[:60])}
    sessions = ss.get("sessions", ss)
    by_ses = {}
    total_a = 0
    for v in sessions:
        a = sum(1 for x in (v.get("turns") or []) if (x.get("role") or "") == "assistant")
        by_ses[v.get("id")] = a
        total_a += a
    short, over = [], []
    for sid in set(list(by_ses) + list(by_log)):
        a, b = by_ses.get(sid, 0), by_log.get(sid, 0)
        if a > b:
            short.append({"session": sid, "sessions_json": a, "log": b, "missing": a - b})
        elif b > a:
            over.append({"session": sid, "sessions_json": a, "log": b, "extra": b - a})
    short.sort(key=lambda x: -x["missing"])
    over.sort(key=lambda x: -x["extra"])
    return {
        "ok": True,
        "sessions_json_assistant": total_a,
        "log_rows": len(log_rows),
        "missing_total": sum(x["missing"] for x in short),
        "extra_total": sum(x["extra"] for x in over),
        "sessions_short": short,
        "sessions_over": over,
        "note": "★ 两个方向都报：漏记（sessions 多）与多记（账多）**不可互相遮盖**",
    }


def _integrity_b31() -> dict:
    """★★ B-31：四本账的完整性校验（★ 复用 "trace_chain_gate"，不重写）。"""
    try:
        import importlib.util as _iu
        sp = _iu.spec_from_file_location("_tcg2", str(APP / "trace_chain_gate.py"))
        m = _iu.module_from_spec(sp)
        sp.loader.exec_module(m)
        d = m.survey()
        return {"ok": bool(d.get("ok")),
                "ledgers": {k: {"rows": v.get("rows"), "chain": v.get("chain"),
                                "covered": bool(v.get("covered")), "why": v.get("why")}
                            for k, v in (d.get("ledgers") or {}).items()}}
    except Exception as e:                                      # noqa: BLE001
        return {"ok": False, "why": "{0}: {1}".format(type(e).__name__, str(e)[:60])}


def _chains_health() -> dict:
    """★ 四本账的链状态（★ 只报不改；★ 取不到就**不报**）。"""
    out = {}
    ledgers = {
        "session_log": LOG,
        "capability": APP / "data" / "能力边界账.jsonl",
        "fs_access": HIST / "fs_access.jsonl",
        "egress": HIST / "egress.jsonl",
    }
    for k, led in ledgers.items():
        try:
            cs = chain_status(led)
            out[k] = {"rows": cs.get("rows"), "chain": cs.get("chain"),
                      "ok": bool(cs.get("ok")), "why": cs.get("why")}
        except Exception as e:                                  # noqa: BLE001
            out[k] = {"ok": False, "why": "{0}: {1}".format(type(e).__name__, str(e)[:50])}
    return out


def health() -> dict:
    """★★ **周期自检入口**（O-4 处置）：把 §13.4 全判据的读数汇成**一条可复核的selfcheck**。

    ★ 它**不改任何判据**（判据所有权在正本 + `checks\落款校验.py`）；
      它只做"跑一遍、汇总、回显口径"，好让**下一版修订有内生输入**，
      而不是等价于"等下一次外部检查"。
    ★ 两条纪律照旧：**不可核 ≠ 通过** · **口径必须回显**。
    """
    c = load_check()
    rows = _rows()
    n = len(rows)
    out: dict = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rounds": n,
        "check_src": str(next((p for p in CHECK_PATHS if p.exists()), "")),
        "profile_id": getattr(c, "PROFILE_ID", None),
        "repeat_threshold": getattr(c, "REPEAT_THRESHOLD", None),
        "signal_table_sha256": getattr(c, "SIGNAL_TABLE_SHA", None),
        "cutover": getattr(c, "DEFAULT_CUTOVER", None),
    }
    if not n:
        out["note"] = "账里还没有轮 ⇒ 无法自检"
        return out
    # 每条判据的红/绿/不可核
    tal: dict = {}
    for r in rows:
        for k, v in (r.get("judgements") or {}).items():
            tal.setdefault(k, {"red": 0, "green": 0, "uncomputable": 0})[v] += 1
    out["by_criterion"] = tal
    never = sorted(k for k, v in tal.items() if v["red"] == 0)
    out["never_red"] = never
    # ★ 报红归因：表的缺陷 vs 执行的错（O-2 的关键读数）
    mm = sum((r.get("map_split") or {}).get("map_miss_n", 0) for r in rows)
    lm = sum((r.get("map_split") or {}).get("layer_mismatch_n", 0) for r in rows)
    out["attribution"] = {"map_miss": mm, "layer_mismatch": lm}
    # ★ 映射表覆盖率（"表够不够用"的直接读数）
    era = [r for r in rows if r.get("层依据")]
    cov = 0
    try:
        cov = sum(1 for r in era if c.layers_from(r.get("层依据") or ""))
    except Exception:                                           # noqa: BLE001
        pass
    out["mapping"] = {
        "evidence_rounds": len(era),
        "covered": cov,
        "coverage_pct": round(100.0 * cov / max(1, len(era)), 1),
        "table_words": sum(len(v) for v in getattr(c, "SIGNAL_KEYWORDS", {}).values()),
    }
    # ⑦ 诚实项：没判据一律红，也不会把"不可核"当通过
    # ★★ 建议 5（v3.7 加）：把「**未到期**」从「不可核」里拆出来。
    #   为什么：新增判据（如推论三条）在生效时刻之前一律 uncomputable，
    #   **与「判据坏掉」读数同形** ⇒ 第一次真判会被误读成「判据突然开始报错」。
    #   ★ 只加汇总，**不改状态枚举**（底端仍只吐 uncomputable）。
    #   ⚠ 判据文案来自 `checks\落款校验.py` 的 detail 措辞 —— **它一改，本处即失效**（故与底同步）。
    _nye = 0
    _nye_by = {}
    for _r in rows:
        for _f in (_r.get("judgement_detail") or []):
            if _f.get("verdict") == "uncomputable" and "早于推论判据生效时刻" in (_f.get("detail") or ""):
                _nye += 1
                _k = _f.get("name") or "?"
                _nye_by[_k] = _nye_by.get(_k, 0) + 1
    out["not_yet_effective"] = {"total": _nye, "by_criterion": _nye_by}
    # ★★ B-32（v3.7 接）：把 `direction_history.reconciliation()` 接进自检。
    #   为什么：它**已实现、调用点 0**（“两本账分工表”只能靠人跑 CLI）⇒ **接上就跑**。
    #   ★ 它回答的是「**哪本账收什么、谁写的、两侧有没有重复记**」。
    #   ★ 载不到就**不报**（不静默降级成“对账通过”）。
    try:
        import direction_history as _dh
        out["reconciliation"] = _dh.reconciliation()
    except Exception as _e:                                    # noqa: BLE001
        out["reconciliation"] = {"ok": False, "why": "未接：{0}".format(str(_e)[:80])}
    # ★★ 建议 1：漏记计数器（新增）
    # ★★ 步 6（B-43）：**健康里报四本账的链状态**（★ 含"条数不符"——
    #   那是链唯一抳不住的那一类：**有行绕过了写链**）。
    out["chains"] = _chains_health()
    # ★★ B-31：四本账的**完整性**（★ 与 chains 同源但**多一层判定**：
    #   ★ "chains" 只报三个数；本项报**"覆盖了没有"与为什么**。)
    out["integrity_b31"] = _integrity_b31()
    # ★★ D-1.4：材料纪元（★ 只读：★ 让「前 B-30 纪元」不被误读成「这一轮没有材料」）
    # ★★ 「不算输出」的计数（v3.7 · 2026-10-08）
    #   ★ 为什么要**单独计**：★ 它不是一条红，而是**整轮定性**
    #     ★ 故**不混进红项合计**（★ 避它被当成"又一条红"而麻木）。
    out["not_output"] = not_output_census()
    out["material_era"] = era_census()
    out["ledger_completeness"] = ledger_completeness()
    out["not_passed"] = "★ `uncomputable` 与 `never_red` 都**不等于通过** —— 只说明没撞到"
    return out


def health_line() -> str:
    """把 `health()` 压成**一行**，便于每 N 轮打印/留痕。

    ⚠️ 首版写成「… 红 {N} · … map_miss {M} / 真红 {K} …」，而 `真红` 其实只指
       `layer_vs_evidence` 的 `layer_mismatch`（**层与依据真的不符**），
       与开头那个「红」（**全部判据的红项合计**）不是一个量
       ⇒ 读起来像**自相矛盾**（"红 68 · 真红 0"）。
       ★ 已改成无歧义写法：`红项合计` 与 `其中层与依据不符`。
    """
    h = health()
    a = h.get("attribution") or {}
    m = h.get("mapping") or {}
    tal = h.get("by_criterion") or {}
    red = sum(v.get("red", 0) for v in tal.values())
    unc = sum(v.get("uncomputable", 0) for v in tal.values())
    _lc = h.get("ledger_completeness") or {}
    _miss = ""
    _ch = h.get("chains") or {}
    _bad = [k for k, v in _ch.items() if not v.get("ok")]
    _chain_s = ""
    _era = h.get("material_era") or {}
    _era_s = ""
    _no = h.get("not_output") or {}
    if _no:
        _era_s += " \u00b7 \u4e0d\u7b97\u8f93\u51fa {0}".format(_no.get("\u4e0d\u7b97\u8f93\u51fa") or 0)
    if _era:
        _old = (_era.get("前 B-30 纪元") or 0) + (_era.get("无材料档") or 0)
        _era_s = " \u00b7 \u6750\u6599\u7eaa\u5143 \u4e59{0}/\u524dB-30 {1}".format(
            _era.get("乙档") or 0, _old)
    _b31 = h.get("integrity_b31") or {}
    if _b31:
        _nc = sum(1 for v in (_b31.get("ledgers") or {}).values() if v.get("covered"))
        _chain_s = " \u00b7 B-31 {0}/4".format(_nc)
    if _ch:
        _chain_s = " \u00b7 \u94fe {0}/4 合".format(len(_ch) - len(_bad))
        if _bad:
            _chain_s += "\uff08\u2605\u4e0d\u5408\uff1a" + "/".join(sorted(_bad)) + "\uff09"
    if _lc.get("ok") and _lc.get("missing_total"):
        _miss = " · ★漏记 {0}（{1} 会话）".format(_lc.get("missing_total"), len(_lc.get("sessions_short") or []))
    _nye = (h.get("not_yet_effective") or {}).get("total", 0)
    _nye_s = (" · 其中未到期 " + str(_nye)) if _nye else ""
    return ("selfcheck | 轮 {0} | 判据 {1} 条 | 红项合计 {2} · 不可核 {3}{9} | "
            "其中层与依据不符 {4}（表未覆盖 {5}）| 映射覆盖率 {6}% | 从未真红 {7} 条 | 口径 {8}").format(
        h.get("rounds"), len(tal), red, unc,
        a.get("layer_mismatch"), a.get("map_miss"),
        m.get("coverage_pct"), len(h.get("never_red") or []),
        str(h.get("signal_table_sha256"))[:12] + "…", _nye_s) + _miss + _chain_s + _era_s

# [health:END]

def report() -> str:
    rs = _rows()
    L = ["# 会话侧持久层 · 复算（装载件 §13.2）", "",
         "> 账：`{0}` ｜ 生成于 {1}".format(LOG, time.strftime("%Y-%m-%d %H:%M:%S")), ""]
    n = len(rs)
    L.append("轮数 **{0}**".format(n))
    L.append("")
    if not n:
        L.append("（账里还没有轮）")
        return "\n".join(L)
    L += ["| 七项 | 命中轮数 | 命中率 |", "| --- | --- | --- |"]
    for f in FIELDS:
        hit = sum(1 for r in rs if r.get(f) not in (None, [], ""))
        L.append("| {0} | {1}/{2} | {3:.1f}% |".format(f, hit, n, 100.0 * hit / n))
    # ★★ §13.4 判据读数（委派给正本可执行底；★ 从此**直接建在会话侧账上**）
    jagg: dict = {}
    for r in rs:
        for k, v in (r.get("judgements") or {}).items():
            jagg.setdefault(k, {}).setdefault(v, 0)
            jagg[k][v] += 1
    if jagg:
        L.append("")
        L.append("## ★★★ §13.4 判据读数（**建在会话侧账上**，委派 `checks\\落款校验.py`）")
        L.append("")
        L.append("| 判据 | 红 | 绿 | 不可核 |")
        L.append("| --- | --- | --- | --- |")
        for k in sorted(jagg):
            c = jagg[k]
            L.append("| {0} | {1} | {2} | {3} |".format(
                k, c.get("red", 0), c.get("green", 0), c.get("uncomputable", 0)))
        cm = next((r.get("check_meta") for r in reversed(rs) if r.get("check_meta")), None)
        if cm:
            L.append("")
            L.append("★ **口径回显**（取自可执行底，**不自己编**）：`{0}`".format(cm.get("profile_id")))
            L.append("  重复阈值 `{0}` · 映射表指纹 `{1}…` · cutover `{2}`".format(
                cm.get("repeat_threshold"), str(cm.get("signal_table_sha256"))[:16], cm.get("cutover")))
            L.append("  ★ `不可核` **不等于**通过 —— v3.5 前的存量轮本就无 `层依据` 栏。")
        # ★★★ 「表的缺陷」vs「执行的错」—— 分开计数（否则假警报会淹没真警报）
        mm = sum((r.get("map_split") or {}).get("map_miss_n", 0) for r in rs)
        lm = sum((r.get("map_split") or {}).get("layer_mismatch_n", 0) for r in rs)
        if mm or lm:
            L.append("")
            L.append("## ★★★ 报红的**归因拆分**（表的缺陷 vs 执行的错）")
            L.append("")
            L.append("| 类 | 条数 | 是什么 |")
            L.append("| --- | --- | --- |")
            L.append("| **`map_miss`** | **{0}** | ★ **判据表未覆盖该表达** —— **表的缺陷**，不是执行者的错 |".format(mm))
            L.append("| **`layer_mismatch`** | **{0}** | 表能推出层、写的层超出它 —— **执行的错** |".format(lm))
            L.append("")
            if mm and not lm:
                L.append("★★ **读法（要紧）**：本批报红**全是表的缺陷** ⇒ `layer_vs_evidence` "
                         "当前**在度'表够不够用'，不是在度'层对不对'**。")
                L.append("  ⇒ 这条红**不能**当「模型判错层」看；它是**给表作者的反馈**。")
            L.append("  ★ 两类**不许合并**（报告建议②）：混合计数会让假警报淹没真警报。")
    L.append("")
    from collections import Counter
    forms = Counter(r.get("落款形态") for r in rs)
    L.append("落款形态分布：" + " · ".join(
        "{0}（{1}）={2}".format(k, FORM_NAMES.get(k, "?"), v) for k, v in sorted(
            forms.items(), key=lambda kv: (kv[0] is None, kv[0]))))
    ev = Counter()
    for r in rs:
        for k in (r.get("events") or {}):
            ev[k] += 1
    L.append("")
    L.append("事件标注：" + (" · ".join("{0}={1}".format(k, v) for k, v in ev.items()) or "（无）"))
    und = sum(1 for r in rs if r.get("undeclared"))
    L.append("")
    L.append("★ 带 `undeclared` 的轮 = **{0}/{1}**（提不出的项已显式列出，**未静默留空**）".format(und, n))
    # ★★ v3.5：`层` 缺有两种，意思完全不同，**不许混成一句**（正本：只报输入、不报结论，`层` 可省）
    v35 = sum(1 for r in rs if r.get("层缺失性质") == "v3.5-有层依据-层可省（合法）")
    real = sum(1 for r in rs if r.get("层缺失性质") == "真未给")
    L.append("")
    L.append("★ **`层` 缺失的性质**（v3.5 修订后必须分开看）：")
    L.append("  · **有 `层依据` ⇒ 层可省（合法）** = **{0}** 轮 —— ★ 这不是缺失，是正本 §13 规定的形态".format(v35))
    L.append("  · **真未给**（连依据也没有）= **{0}** 轮 —— 这才是要追的".format(real))
    return "\n".join(L)


# ---------------------------------------------------------------------------
# 四、自测（正反两向）
# ---------------------------------------------------------------------------

#: 该解析出来的（正对照）
POSITIVE = [
    ("常态·走过位",
     "……结论。\n\n思考位：M3 M4 A3（层：事 · 位来源：层选 · 自检：未触发 · 锚：3/3）\n"
     "显化声明：本回答是显化，不是根。",
     {"位集": ["M3", "M4", "A3"], "层": "事", "位来源": "层选", "落款形态": 1}),
    ("★ 形态 4：最小入口档，位集写空",
     "……那你现在在哪里？\n\n思考位：（层：明 · 位来源：层选 · 自检：未触发）\n"
     "显化声明：本回答是显化，不是根。",
     {"位集": [], "落款形态": 4}),
    ("★ 形态 5：不适用档，位集写空",
     "这是一首关于秋天的诗。\n\n思考位：（不适用 · 位集为空）\n"
     "形态5判定：句「帮我写一首关于秋天的诗」｜明层:未命中（问的是创作不是认知） · "
     "时层:未命中（无关节奏） · 事层:未命中（无排序诉求） · 己层:未命中（不涉边界）\n"
     "显化声明：本回答是显化，不是根。本问题不适用层位框架。",
     {"位集": [], "落款形态": 5}),
    ("自检触发档",
     "……自检结论。\n\n思考位：M1 M4 T1 A1 A3 S1（层：层判不明 · 位来源：兜底 · 自检：触发 · 锚：3/3）\n"
     "显化声明：本回答是显化，不是根。",
     {"位集": ["M1", "M4", "T1", "A1", "A3", "S1"], "是否层判不明": True, "落款形态": 2}),
]

#: 不该误判的（负对照）
NEGATIVE = [
    ("普通创作，无落款",
     "秋天来了，叶子落了。这首诗写完了。", {"落款形态": None}),
    ("正文提到'思考位'但不是落款",
     "我建议你在思考位、视角这些词上别纠缠。", None),      # 只要求"不崩、不误报形态 4/5"
]


def rebuild(sessions_json: pathlib.Path = None, log: pathlib.Path = LOG,
            dry: bool = True) -> dict:
    """★ **重算**会话侧账里每一行（解析器修了以后，旧行可能存了假值）。

    为什么需要：解析器的 bug 会把**正文里的垃圾串**当成字段存进账
    ⇒ 那几行的账是**假的**，而账是"唯一能被对账的地方"，留着假的比没有更坏。

    怎么重算：`session_log` 每行存了 `session` + `reply_sha256` + `材料指纹.sha256`
    ⇒ 用 `sessions.json` 里的**原文**按 `reply_sha256` 找回那一轮，用**修好的**解析器重算七项。
    ★ 找不到原文的行（例如 8399 验证轮）**保留原样**，并在结果里单列出来（不静默丢）。

    默认 `dry=True`（只报差异）。真要写，显式 `dry=False`。
    """
    sj = sessions_json or (APP / "data" / "sessions.json")
    rows = _rows(log)
    if not sj.exists():
        return {"error": "找不到 {0}".format(sj)}
    ss = json.loads(sj.read_text(encoding="utf-8"))
    sess = {s["id"]: s for s in ss.get("sessions", ss)}

    # reply_sha256 -> 那一轮的 assistant 原文
    byhash: dict = {}
    for sid, s in sess.items():
        for t in s.get("turns", []):
            if t.get("role") == "assistant":
                h = hashlib.sha256(str(t.get("content", "")).encode("utf-8")).hexdigest()
                byhash[h] = str(t.get("content", ""))

    changed, unmatched, out = [], [], []
    for r in rows:
        txt = byhash.get(r.get("reply_sha256"))
        if txt is None:
            unmatched.append(r)
            out.append(r)                    # ★ 保留原样，不猜
            continue
        det = parse_footer(txt)
        new = dict(r)
        for k in ("位集", "位来源", "层", "层依据", "层依据带引号", "有无层依据栏",
                  "是否层判不明", "M4 反方条件", "落款形态", "落款形态说明",
                  "f5_sentence", "f5_present", "f5_quad", "是否带落款", "位集档",
                  "delegated", "delegated_to", "undeclared", "层缺失性质"):
            if k in det:
                new[k] = det[k]
        # 事件标注也要重算（它依赖位集）
        new["events"] = annotate_events({**det, "_正文": txt})
        # ★★ 判据读数一并重算（解析口径变了 ⇒ 判据读数也必须跟着重算，不能只重算字段）
        findings, _m = judge_round_delegate(txt, material="", ts=new.get("ts"))
        new["judgements"] = {f.get("name"): f.get("verdict") for f in findings}
        new["judgement_detail"] = [{"name": f.get("name"), "verdict": f.get("verdict"),
                                    "detail": (f.get("detail") or "")[:160]} for f in findings]
        new["red"] = sorted({f.get("name") for f in findings if f.get("verdict") == "red"})
        new["green"] = sorted({f.get("name") for f in findings if f.get("verdict") == "green"})
        new["uncomputable"] = sorted({f.get("name") for f in findings
                                      if f.get("verdict") == "uncomputable"})
        new["map_split"] = map_miss_split(findings, new.get("层依据") or "")
        new["check_meta"] = check_meta()
        for k in ("位集", "位来源", "层", "层依据", "是否层判不明", "M4 反方条件", "落款形态"):
            if r.get(k) != new.get(k):
                changed.append({"ts": r.get("ts"), "session": r.get("session"),
                                "field": k, "was": r.get(k), "now": new.get(k)})
        out.append(new)

    if not dry:
        # ★★ 建议 7（v3.7 加）：**全量重写前先备份**。★ 原实现在这里没有任何备份动作（实测），
        #   一次 `--rebuild --write` 就能静默覆盖原账。★ 命名与 `_history\_backups\` 同一套。
        _bkname = backup_ledger(log, why="rebuild")
        log.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in out),
                       encoding="utf-8", newline="\n")
    return {
        "log": str(log), "rows": len(rows), "rewritten": not dry,
        "changed_fields": len(changed), "changed": changed[:40],
        "unmatched_rows_kept": len(unmatched),
        "unmatched_ts": [r.get("ts") for r in unmatched],
    }


def _selftest() -> int:
    ok = True

    def ck(label, cond, extra=""):
        nonlocal ok
        if not cond:
            ok = False
        print("  {0} {1}{2}".format("✅" if cond else "❌", label,
                                    ("  —— " + extra) if extra else ""))

    print("[session_log] 自测 · 会话侧持久层（§13.2 七项 + 事件标注）")
    print()
    print("①a ★★ 落款形态以**正本可执行底**为准（§13.4 只在'落款条款'上分档）")
    # ★ 为什么这条期望与首版不同：底自己写着
    #     `out["form"] = 1  # 形态 1 / 2 / 3 在落款条款上同构（都要求 层依据）`
    #   ⇒ 它把 1/2/3 都记成 1，且**不细判 4 vs 1**（两者落款条款同构 —— 都要求 层依据）。
    #   ★ 故我原来的期望（自建分档）**是我错**；权威是它。我另用 `位集档` 记"空/非空"。
    for name, txt, want in POSITIVE:
        d = parse_footer(txt)
        ck("{0} · delegated={1}".format(name, d.get("delegated")),
           d.get("delegated") is True, "底 = {0}".format((d.get("delegated_to") or "")[-24:]))
    ck("★ 形态1（常态）—— 底记 1", parse_footer(POSITIVE[0][1])["落款形态"] == 1)
    ck("★ 形态4候选（空位集）—— 底**也**记 1（落款条款同构）",
       parse_footer(POSITIVE[1][1])["落款形态"] == 1,
       "底 form={0}".format(parse_footer(POSITIVE[1][1])["落款形态"]))
    ck("★ 形态5（不适用）—— 底记 5", parse_footer(POSITIVE[2][1])["落款形态"] == 5)
    ck("★ 形态2/3候选 —— 底记 3（落款条款同构，它归 3）",
       parse_footer(POSITIVE[3][1])["落款形态"] == 3)
    print("     ★ 我的**另一条轴**（`位集档`，本件自己的标注，**不冒充 §13.4 的形态**）：")
    for name, txt, _w in POSITIVE:
        d = parse_footer(txt)
        print("       {0:<32} 位集档={1} 位集={2}".format(name[:30], d.get("位集档"), d.get("位集")))

    print()
    print("①b ★ 四族都要取到（M/T/A/S —— 首版漏了 S 族）")
    d_all = parse_footer("思考位：M1 M4 T1 A1 A3 S1 S3（层：明+事+己 · 位来源：层选 · 自检：未触发）")
    ck("S 族的位取到了", "S1" in d_all["位集"] and "S3" in d_all["位集"],
       str(d_all["位集"]))
    ck("四族都在", {p[0] for p in d_all["位集"]} == {"M", "T", "A", "S"},
       str(sorted({p[0] for p in d_all["位集"]})))

    print()
    print("①c ★★ 正文里的「层：」不许被当成落款字段（**真 bug 的回归**）")
    # 这是从真账里抓到的失效输入：落款是形态 5，而**正文**里有一句 `层：没有。`
    BAD = ("思考位：（无 · 本问题不适用层位框架——问的是我的能力边界，未命中四层信号中的任何一条）\n"
           "显化声明：本回答是显化，不是根。\n\n"
           "**持久层**\n- 层：没有。检索工具：没有。**\n\n具体说清楚：\n")
    db = parse_footer(BAD)
    ck("★ 层没被正文污染（不是那句垃圾）", db["层"] in (None, "未命中四层信号"),
       repr(db["层"]))
    ck("★ 落款形态仍是 5（不适用档）", db["落款形态"] == 5, str(db["落款形态"]))
    ck("★ 位集写空且**保留**（「没走位」是数据）", db["位集"] == [], str(db["位集"]))
    # 落款自己写得古怪时，也不许把长串存进账
    dlong = parse_footer(
        "思考位：M1（层：" + "很长" * 20 + " · 位来源：层选）\n显化声明：本回答是显化。")
    ck("★ 落款里超长的层 ⇒ 不存进账且进 undeclared",
       dlong["层"] is None and "层" in dlong["undeclared"],
       "层={0!r} undeclared={1}".format(dlong["层"], dlong["undeclared"]))

    print()
    print("①d ★★ 值域检查**两向**都要对（首版只对一向 ⇒ 实测误杀合法值）")
    # 这是从真账里抓到的**合法**落款：`层依据：…` 在前、`层:事*` 在后，且值带标记星号
    REAL = ("思考位：M3 M4 A3（层依据：「排序和资源都卡住了」 · 层:事* · 位来源：层选 · "
            "自检：未触发 · 锚：3/3）\n显化声明：本回答是显化，不是根。")
    dr = parse_footer(REAL)
    ck("★ `层:事*` 被认出来（不是 None）", dr["层"] == "事", repr(dr["层"]))
    ck("★ 没被「层依据：」抢先匹配", "依据" not in str(dr["层"]), repr(dr["层"]))
    ck("★ 位集仍对", dr["位集"] == ["M3", "M4", "A3"], str(dr["位集"]))
    ck("★ 位来源仍对", dr["位来源"] == "层选", repr(dr["位来源"]))
    # 反向：垃圾仍须被挡
    for bad in ("没有。检索工具：没有。**", "很长" * 20):
        ck("垃圾仍被挡：{0!r}".format(bad[:14]), parse_footer(
            "思考位：M1（层：" + bad + " · 位来源：层选）\n显化声明：本回答是显化。")["层"] is None)

    print()
    print("② 负对照（不许误报）")
    for name, txt, want in NEGATIVE:
        d = parse_footer(txt)
        if want is None:
            # ★ 不许把"正文提到思考位"当成"有落款 + 走位"
            ck(name, not (d.get("落款形态") == 1 and d.get("位集")),
               "落款形态={0} 位集={1}".format(d.get("落款形态"), d.get("位集")))
        else:
            ck(name, all(d.get(k) == v for k, v in want.items()),
               "落款形态={0}".format(d.get("落款形态")))

    print()
    print("③ ★ 不落材料原文（只长度+首20字+sha256）")
    # ⚠️ 首版这条断言写错了：我拿"材料本身"去比，而**首20字指纹**理应与材料前 20 字相同
    #    ⇒ 那句断言**恒假**（假红）。正确的问法是：**除指纹字段外，账里还有没有材料原文？**
    MSG = "这是一段很长的材料" * 10
    fp = material_fingerprint(MSG)
    ck("有 length", fp["length"] > 0)
    ck("head20 长度 ≤ 20", len(fp["head20"]) <= 20, repr(fp["head20"]))
    ck("有 sha256", len(fp["sha256"]) == 64)
    rec = record("__selftest__", MSG, POSITIVE[0][1], log=PROBE)
    # ★ 只有在**抹掉**已知合规的指纹字段之后，账里才**不该**再出现材料
    scratch = dict(rec)
    scratch.pop("材料指纹", None)
    leftover = json.dumps(scratch, ensure_ascii=False)
    ck("★ 除「材料指纹」外，账里**没有**材料原文", MSG not in leftover)
    ck("★ 指纹里 head20 只取了前 20 字", fp["head20"] == MSG[:20])
    ck("★ 指纹里**没有**全文", MSG not in fp["head20"])

    print()
    print("④ 事件标注（不单独开账，写进同一轮）")
    ck("含 M4/A3 ⇒ 标了补位", "补位" in (rec.get("events") or {}), str(rec.get("events")))
    ck("★ 事件在**同一条记录**里（不是另一个文件）", "events" in rec)
    ck("★ 机械判不出的'错位'**不标**（不猜）", "错位" not in (rec.get("events") or {}))

    print()
    print("⑤ ★ fail-closed：提不出的项要显式 undeclared")
    d2 = parse_footer("思考位：M3 M4（层：事 · 自检：未触发）")
    ck("缺 位来源 与 M4反方条件 ⇒ 列进 undeclared",
       "位来源" in d2["undeclared"] and "M4 反方条件" in d2["undeclared"],
       str(d2["undeclared"]))

    print()
    print("⑥ ★ 探针三态（证明能写能读，不靠模型自报）")
    pr = probe()
    ck("能写", pr["can_write"])
    ck("能读回", pr["can_read_back"])
    ck("探针文件已删", pr["probe_file_removed"])
    print("     结论：{0}".format(pr["conclusion"]))

    # 清理自测落在探针文件里的行
    try:
        if PROBE.exists():
            PROBE.unlink()
    except Exception:                                           # noqa: BLE001
        pass

    print()
    print("⑦ ★★ §13.4 判据**建在会话侧账上**（本轮优化：不再绕 sessions.json 重解析）")
    # ★ 用**底自己那条已通过的正例格式**（`checks\落款校验.py` 的正例逐字），
    #   而不是我自己发明的紧凑格式 —— 那边才是"什么算合法"的权威。
    MAT = "我手头几件事排不开：排序/资源 都卡着，不知道先推哪个。"
    GOOD = ("先说结论：先排「资源」再谈「排序」。\n\n"
            "思考位：M3 M4 A3（层依据：「排序/资源」 · 层:事* · 位来源：层选 · 自检：未触发 · 锚：3/3）\n\n"
            "显化声明：本回答是显化，不是根。根不在本回答中。材料：长度 30 + 我手头几件事排不开…")
    r7 = record("__selftest__", MAT, GOOD, log=PROBE)
    ck("解析已委派（delegated=True）", r7.get("delegated") is True,
       (r7.get("delegated_to") or "")[-30:])
    ck("账里带八条判据读数", bool(r7.get("judgements")),
       str(sorted((r7.get("judgements") or {}))))
    ck("账里带口径回显（profile/阈值/映射表指纹/cutover）",
       bool((r7.get("check_meta") or {}).get("profile_id")) and
       bool((r7.get("check_meta") or {}).get("signal_table_sha256")) and
       bool((r7.get("check_meta") or {}).get("cutover")))
    ck("★ v3.5 席位在账里（层依据/带引号/有栏/位集档）",
       r7.get("层依据") == "排序/资源" and r7.get("层依据带引号") is True
       and r7.get("有无层依据栏") is True and r7.get("位集档") == "走位",
       "层依据={0!r} 带引号={1} 有栏={2} 位集档={3!r}".format(
           r7.get("层依据"), r7.get("层依据带引号"),
           r7.get("有无层依据栏"), r7.get("位集档")))
    ck("★ 正例判绿（无红项）", (r7.get("red") or []) == [], str(r7.get("red")))
    # ★ 负例：`层依据` 写「无」⇒ 必须红（借底自己的负例口径）
    BAD = ("先说结论。\n\n思考位：M3 M4 A3（层依据：「无」 · 层:事* · 位来源：层选 · 自检：未触发）\n"
           "显化声明：本回答是显化，不是根。")
    jb, _m = judge_round_delegate(BAD, material=MAT, ts="2026-10-06 13:00:00")
    names = {f["name"]: f["verdict"] for f in jb}
    ck("★ 负例判红：`层依据` 写「无」⇒ layer_evidence_present=red",
       names.get("layer_evidence_present") == "red", str(names.get("layer_evidence_present")))
    # ★ 而负例的判据读数也要**进账**（不只是函数返回）
    r7b = record("__selftest__", MAT, BAD, log=PROBE)
    ck("★ 负例的红项**进了账**（不是只算不落）",
       "layer_evidence_present" in (r7b.get("red") or []), str(r7b.get("red")))
    try:
        if PROBE.exists():
            PROBE.unlink()
    except Exception:                                           # noqa: BLE001
        pass

    print()
    print("⑧ ★★ 报红归因：`map_miss`（表的缺陷）vs `layer_mismatch`（执行的错）")
    # ① 表的缺陷：依据里没有表内任何关键词
    f1, _m1 = judge_round_delegate(
        "思考位：M3 M4 A3（层依据：「重新诊断，给到优化建议」 · 层:明+事* · 位来源：层选 · 自检：未触发）\n"
        "显化声明：本回答是显化，不是根。", material="重新诊断，给到优化建议",
        ts="2026-10-06 13:00:00")
    s1 = map_miss_split(f1, "重新诊断，给到优化建议")
    ck("★ 表的缺陷 ⇒ 记 map_miss（且 mismatch=0）",
       s1["map_miss_n"] == 1 and s1["layer_mismatch_n"] == 0,
       "map_miss={0} mismatch={1}".format(s1["map_miss_n"], s1["layer_mismatch_n"]))
    # ② 执行的错：依据能落进表（含“排序”），但写的层超出推出的层集
    f2, _m2 = judge_round_delegate(
        "思考位：M3 M4 A3（层依据：「排序」 · 层:己 · 位来源：层选 · 自检：未触发）\n"
        "显化声明：本回答是显化，不是根。", material="排序",
        ts="2026-10-06 13:00:00")
    s2 = map_miss_split(f2, "排序")
    ck("★ 执行的错 ⇒ 记 layer_mismatch（且 map_miss=0）",
       s2["layer_mismatch_n"] == 1 and s2["map_miss_n"] == 0,
       "map_miss={0} mismatch={1}".format(s2["map_miss_n"], s2["layer_mismatch_n"]))
    # ③ 负对照：判绿的一轮**两类都不该记**
    f3, _m3 = judge_round_delegate(GOOD, material=MAT, ts="2026-10-06 13:00:00")
    s3 = map_miss_split(f3, "排序/资源")
    ck("★ 判绿 ⇒ 两类都为 0（不许误记）",
       s3["map_miss_n"] == 0 and s3["layer_mismatch_n"] == 0,
       "map_miss={0} mismatch={1}".format(s3["map_miss_n"], s3["layer_mismatch_n"]))

    print()
    print("⑨ ★★ 跨轮判据 `same_layer_evidence_repeat` 必须**真被判**（单轮路算不出它）")
    # 造三段**同一 `层依据`** 的轮 ⇒ 跨轮判据应报红（阈值 3）
    SAME = "排序和资源都卡住了"
    rs9 = [{"text": ("思考位：M3 M4 A3（层依据：「{0}」 · 层:事* · 位来源：层选 · 自检：未触发）\n"
                     "显化声明：本回答是显化，不是根。".format(SAME)),
            "ts": "2026-10-06 14:0{0}:00".format(i)} for i in range(3)]
    b9 = load_check().judge_batch(rs9)
    v9 = None
    for res in b9.get("rounds", []):
        for f in (res.get("findings") or []):
            if f.get("name") == "same_layer_evidence_repeat":
                v9 = f.get("verdict")
    ck("★ 同片段跨 3 轮 ⇒ 跨轮判据报红（阈值 3）", v9 == "red", str(v9))
    # 负对照：三个**不同**片段 ⇒ 不该报红
    rs9b = [dict(rs9[i], text=rs9[i]["text"].replace(SAME, ["甲", "乙", "丙"][i])) for i in range(3)]
    b9b = load_check().judge_batch(rs9b)
    v9b = {f["verdict"] for res in b9b.get("rounds", [])
           for f in (res.get("findings") or [])
           if f.get("name") == "same_layer_evidence_repeat"}
    ck("★ 三个不同片段 ⇒ 跨轮判据**不报红**（负对照）", "red" not in v9b, str(v9b))

    print()
    print("  [{0}] ".format("OK" if ok else "X") + ("全部通过" if ok else "**有未通过**"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="会话侧持久层（装载件 §13.2 七项）")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--tail", type=int, default=0)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--health", action="store_true",
                    help="★ 周期自检入口：汇总 §13.4 全判据读数（不改判据）")
    ap.add_argument("--health-json", action="store_true", help="同上，机器可读")
    ap.add_argument("--chain", action="store_true",
                    help="★ B-43：链对账（链条数 vs 账行数 + 自校）")
    ap.add_argument("--chain-json", action="store_true", help="同上，机器可读")
    ap.add_argument("--pending", action="store_true",
                    help="只列待批的机制层修订候选（不给机制层做任何改动）")
    ap.add_argument("--rebuild", action="store_true",
                    help="★ 用 sessions.json 的原文按修好的解析器**重算**账里每一行（默认只报差异）")
    ap.add_argument("--write", action="store_true",
                    help="与 --rebuild 同用：真的写回（不给就是 dry-run）")
    ap.add_argument("--cross-round", action="store_true",
                    help="★ 重算**跨轮**判据 `same_layer_evidence_repeat`（单轮路算不出来的那一条）")
    a = ap.parse_args()
    if a.cross_round:
        r = recompute_cross_round(dry=not a.write)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        if not a.write:
            print()
            print("  ★ 这是 **dry-run**（没写）。要写回请加 `--write`。")
        return 0
    a = ap.parse_args()
    if a.rebuild:
        r = rebuild(dry=not a.write)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        if not a.write:
            print()
            print("  ★ 这是 **dry-run**（没写）。要写回请加 `--write`。")
        return 0
    if a.chain or a.chain_json:
        cs = chain_status()
        if a.chain_json:
            print(json.dumps(cs, ensure_ascii=False, indent=2))
        else:
            print("★ B-43 链对账")
            print("  账   {0} · {1} 行".format(cs["ledger"], cs["rows"]))
            print("  链   {0} 条".format(cs["chain"]))
            print("  判   {0} —— {1}".format("★ 合" if cs["ok"] else "⚠ 不合", cs["why"]))
        return 0 if cs["ok"] else 1
    if a.selftest:
        return _selftest()
    if a.probe:
        print(json.dumps(probe(), ensure_ascii=False, indent=2))
        return 0
    if a.tail:
        for r in _rows()[-a.tail:]:
            print("{0} | {1:<10} | 形态{2} | 位集={3} | 层={4} | 来源={5} | undeclared={6}".format(
                r.get("ts"), str(r.get("session"))[:10], r.get("落款形态"),
                r.get("位集"), r.get("层"), r.get("位来源"), r.get("undeclared")))
        return 0
    if a.health:
        print(health_line())
        print(criterion_status_line())          # ★ B-40：判据落实状况
        print(pending_line())          # ★ 顺带报待批账，免得"先积累"变成"忘掉"
        return 0
    if a.pending:
        it = pending_items()
        print("待批 · 机制层修订候选（{0} 条）—— 按「先积累再一起改」，未动机制层".format(len(it)))
        for x in it:
            print("  {0}  {1}   [{2}]".format(x["id"], x["title"], x["fix_or_extend"]))
        print()
        print("  账：{0}".format(PENDING_FILE))
        return 0
    if a.health_json:
        print(json.dumps(health(), ensure_ascii=False, indent=2))
        return 0
    if a.report:
        t = report()
        print(t)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
