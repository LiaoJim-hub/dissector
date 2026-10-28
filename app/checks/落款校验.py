#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""落款校验 · 落款判据的**可执行底**（v3.6 · ★ 外发版：口径真值在包内 = 本件 --selftest）

★ 它解决的是什么
  §13 的落款此前**只报结论（层名）**，不报**输入（依据）** ⇒
  「机制验证了"东西在不在"，没验证"东西对不对"」（REQ·三处出口改动 · 病根）。
  ⇒ 本件把 §13.4 判据总表落成**能跑的东西**：
       --selftest   验收（3 负例 + 1 正例 + v3.6 新增 2 负例；另有反向探针）
       --scan       扫会话侧，出**真实读数**（含"空转"= 跨轮重复）

★ v3.6 改动（对应 A 检查报告四条阻断 / 应修）
  ① `层:<层>*` 逃逸封堵：推定标记 `*` 在层集比对**前剥掉**（此前 `层:明*` 假绿）；
  ② 新增第 9 条判据 `source_present`（缺 `位来源` / 值不在 层选|指定|兜底 ⇒ 红）；
  ③ 无时间戳的轮次 **fail-closed** ⇒ 全判据 `uncomputable`（批量路径；--text 仍按 v3.5 时代处理）；
  ④ `layer_vs_evidence` 红项分栏：`map_miss` / `layer_mismatch`（finding 带 `kind` 字段，scan 分开计数）。

★ 与文本的关系
  **冲突时以本件为准**（装载件文首「底 > 呈现」条）。
  ★ 外发版（★ 2026-10-13 修悬空引用 —— 敌手D 第10轮 V-5）：★ 本包**没有**《装载件》那一级文件
  ⇒ ★ 口径真值 = **本件文首所列 + --selftest 所验**；改本件任何口径 ⇒ 必须连 --selftest 一起改并回显。

★ 三条纪律（与 §13.4 同）
  1. **不可核 ≠ 通过**：一律 `uncomputable`，**不许静默判绿**；
  2. **口径随读数走**：`normalized_by` / `repeat_threshold` / 映射表指纹 / `cutover`，**必须回显**；
  3. **红项只触发人看**：**不做身份 / 排行 / 裁决**。

用法：
    python 落款校验.py --selftest                      # 验收
    python 落款校验.py --scan                          # 扫会话侧（真实读数）
    python 落款校验.py --scan --json                   # 机器可读
    python 落款校验.py --text 某轮.md --material 材料.md  # 校验单轮（无 ts ⇒ 按 v3.5 时代处理）
    python 落款校验.py --cutover "2026-10-06 12:35:00"  # 覆盖"判据生效时刻"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ------------------------------------------------------------------ 口径（与 §13.4 逐字一致）
PROFILE_ID = "nfkc+collapse_ws+strip_punct+lower@v1"
REPEAT_THRESHOLD = 3
LAYER_EVIDENCE_MAX = 20
FORM5_SENTENCE_MAX = 30

#: 空填 / 无依据 的显式取值（命中即 `layer_evidence_present` 红）
EMPTY_EVIDENCE = {"", "无", "无。", "（无）", "无)", "-", "—", "略", "综合判断", "综合", "n/a"}

#: ★ 关键词映射表（与 §七 逐字一致）；判据 `layer_vs_evidence` 的唯一依据
SIGNAL_KEYWORDS = {
    "明": ("怎么看", "是什么", "哪个对", "方向", "定位"),
    "时": ("节奏", "时机", "累了没", "推进与休整", "透支"),
    "事": ("做什么", "排序", "资源", "推进受阻", "具体执行"),
    "己": ("边界", "坚持", "外部反馈", "独处状态", "自我要求"),
}
LAYER_ORDER = ("明", "时", "事", "己")

SIGNAL_TABLE_CANON = "\n".join(
    "{0} → {1}".format(k, " / ".join(v)) for k, v in SIGNAL_KEYWORDS.items()
) + "\n"
SIGNAL_TABLE_SHA = hashlib.sha256(SIGNAL_TABLE_CANON.encode("utf-8")).hexdigest()

#: ★ v3.5 判据生效时刻。此前的轮次**判据晚于账** ⇒ 记 `uncomputable`，**不记红**
#: （★ 这不是"放过"，是"不可核"——存量账里根本没有 `层依据` 这个字段）
#: 取值 = 正本 v3.5 定稿落盘 + 镜像重做完成的时刻（2026-10-06 12:15:51 镜像；取整到分）
DEFAULT_CUTOVER = "2026-10-06 12:16:00"

#: ★ v3.6 判据生效时刻（第 9 条 `source_present` · `层:*` 逃逸封堵自此起算）。
#: 取 v3.6 镜像完成时刻（取整到分）。**注意**：v3.5→v3.6 之间的轮次按 v3.5 判据判（其落款格式与 v3.6 相同，
#: 仅新增的 `source_present` 一条对此前轮次**仍可判**——`位来源` 字段 v3.5 就有，故 cutover 维持 v3.5 时刻不动）。
V36_CUTOVER = DEFAULT_CUTOVER

SOURCE_ENUM = ("层选", "指定", "兜底")

# ★ 本外发版：`--scan` 的默认输入 = **本包的会话账**（★ 相对定位，不带作者机器的绝对路径）。
#   checks\ 在 app\ 下 ⇒ 上三级 = 包根 ⇒ 找 `data\sessions.json`。
DEFAULT_SESSIONS = Path(__file__).resolve().parent.parent.parent / "data" / "sessions.json"

#: ★★ 说明性后缀的**开括号**（v3.8 加 · 2026-10-08 · 持有方裁"落款允许带说明"）。
#:   ★ 实测依据（★ 三行，都是**本意合规**而被判红）：
#:     `位来源：指定（用户明示覆盖路径）` ⇒ 旧法正则读到 `指定（用户明示覆盖路径` ⇒ **不在枚举 ⇒ 假红**
#:     `位来源：层选【本轮改判·原判事+己已作废】` ⇒ 读到 `层选【本轮改判` ⇒ ★ 同上
#:   ★★ **故新增规则**：★ 枚举值**后面**可跟一段说明，★ **用明确的开括号分隔** ⇒ ★ 只取**枚举值本身**。
#:   ★★ **边界必须严**（★ 否则就是"放松判据以通过检查"，★ 那是最坏的修法）：
#:     · ★ **只认这四个开括号**：`（` `(` `【` `[`
#:     · ★ **值本身仍须逐字等于枚举项** —— ★ `指定X（…）` **仍判红**（★ X 不是说明，是另一个值）
#:     · ★ **说明不可省**这一条：★ 本函数**只做取值**，★ **不改变"必须在枚举内"这个要求**
_SUFFIX_OPEN = "（(【["


def _enum_value(raw: str, enum) -> tuple:
    """★ 从 `值（说明）` 里取**枚举值**。返回 `(值, 说明)`；★ 无说明则说明为空串。

    ★ 两条路（★ 都要求**取到的头必须逐字等于枚举项**）：
      ① ★ **开括号切分**：`指定（用户明示覆盖路径）` ⇒ `指定`
      ② ★ **最长前缀兜底**：`层选★★` ⇒ `层选`（★ 尾随强调符/装饰符）
    ★ 两条都不成 ⇒ **原样返回**（★ 让调用方照旧判红 —— ★ 不在这里偷偷放行）。
    """
    s = (raw or "").strip().strip("*_").strip()
    if not s:
        return "", ""
    if s in enum:
        return s, ""
    # ① 开括号切分
    for i, ch in enumerate(s):
        if ch in _SUFFIX_OPEN:
            head = s[:i].strip()
            if head in enum:
                return head, s[i:].strip()
            break
    # ② 前缀兜底（★ **只在余部是纯装饰符时成立**）
    #   ★★ 为何要这个限定（★ A 实测踩出的假放行）：★ `指定X` 的前缀是 `指定`，
    #     ★ 若只按"最长前缀"兜底，★ **`指定X` 会被放行** —— ★ 而 `X` **不是说明，是另一个值**。
    #   ★ 判据：★ **余部含任何字母/数字/汉字 ⇒ 不算说明 ⇒ 不放行**（★ 仍判红）。
    hit = max((e for e in enum if s.startswith(e)), key=len, default="")
    if hit:
        rest = s[len(hit):]
        if rest and not any(ch.isalnum() for ch in rest):
            return hit, rest.strip()
    return s, ""


# ------------------------------------------------------------------ 解析
RE_SIG = re.compile(r"思考位\s*[：:]")
RE_F5_LINE = re.compile(r"形态\s*5\s*判定\s*[：:]")
RE_EVIDENCE_Q = re.compile(r"层依据\s*[：:]\s*[「“\"]([^」”\"]*)[」”\"]")
RE_EVIDENCE_BARE = re.compile(r"层依据\s*[：:]\s*([^·）)\n]*)")
RE_LAYER = re.compile(r"层(?!依据)\s*[：:]\s*([^\s·）)\n]+)")
RE_SOURCE = re.compile(r"位来源\s*[：:]\s*([^\s·）)\n]+)")
RE_SELFCHECK = re.compile(r"自检\s*[：:]\s*([^\s·）)\n]+)")
RE_ANCHOR = re.compile(r"锚\s*[：:]\s*([^\s·）)\n]+)")
RE_F5_SENT = re.compile(r"形态\s*5\s*判定\s*[：:]\s*句\s*[「“\"]([^」”\"]*)[」”\"]")
RE_F5_QUAD = re.compile(r"(明层|时层|事层|己层)\s*[：:]\s*(未命中|命中)\s*(?:[（(]([^）)]*)[）)])?")
RE_DECL = re.compile(r"显化声明\s*[：:]")

#: ★★ 推论判据生效时刻（v3.7 §15 新增・2026-10-07）
#:   为什么要单独一个 cutover：§15.4 那一栏是 v3.7 才有的，
#:   **此前轮次本来就不会写它** ⇒ 若用旧 cutover 去判，
#:   全部历史轮会被记成「该写而未写」的**假红**。
#:   ★ 故：此时刻之前的轮 ⇒ 三条推论判据一律 **uncomputable**（fail-closed）。
INFERENCE_CUTOVER = "2026-10-07 23:15:00"

#: ★ §15.2 五类（逐字）
INFERENCE_TYPES = ("结构推演", "条件推论", "分栏推论", "边界辨认", "开放假设")

RE_ITYPE = re.compile(r"推论类型\s*[：:]\s*([^\s·）)\n]+)")
#: ★ “做了推演”的信号：正文含「若…则…」结构（§15.5 逐字）
RE_IFTHEN = re.compile(r"若[^\n]{1,60}?[，,]?\s*则")
#: ★ “起点”可指认（§15.3 ①）—— 同义词宽容
RE_PREMISE = re.compile(r"起点|假设集|假设|前提|设定集")
#: ★ “返回路径”可指认（§15.3 ⑤、§15.4）
RE_RETURN = re.compile(r"返回路径|作废|失效条件|何时不成立")


def normalize(s: str) -> str:
    """口径 `nfkc+collapse_ws+strip_punct+lower@v1`（★ 改此函数 = 改口径，须同步 §13.4 并回显）。"""
    s = unicodedata.normalize("NFKC", s)
    s = " ".join(s.split())
    s = "".join(ch for ch in s if not unicodedata.category(ch).startswith("P"))
    s = " ".join(s.split())
    return s.lower()


def strip_signature(text: str) -> str:
    """正文 = 全文去掉落款那几行（思考位 / 形态5判定 / 显化声明 之后的部分）。"""
    idx = len(text)
    for pat in (RE_SIG, RE_F5_LINE, RE_DECL):
        m = pat.search(text)
        if m:
            idx = min(idx, m.start())
    return text[:idx]


def parse_signature(text: str) -> dict:
    out = {
        "has_sig": False, "form": None,
        "evidence": None, "evidence_quoted": False, "has_evidence_field": False,
        "layer": None, "source": None, "selfcheck": None, "anchor": None,
        "f5_sentence": None, "f5_present": False, "f5_quad": {},
        "inference_type": None, "inference_type_raw": None,
    }
    m = RE_SIG.search(text)
    if m:
        out["has_sig"] = True
        tail = text[m.start(): m.start() + 600]
        eq = RE_EVIDENCE_Q.search(tail)
        if eq:
            out["evidence"], out["evidence_quoted"], out["has_evidence_field"] = eq.group(1), True, True
        else:
            eb = RE_EVIDENCE_BARE.search(tail)
            if eb:
                out["evidence"], out["has_evidence_field"] = eb.group(1).strip(), True
        for key, pat in (("layer", RE_LAYER), ("source", RE_SOURCE),
                         ("selfcheck", RE_SELFCHECK), ("anchor", RE_ANCHOR)):
            mm = pat.search(tail)
            if mm:
                # ★★ v3.7（2026-10-08）：**剥掉尾部的 Markdown 强调符**。
                #   ★ 实测：落款写成 `**层依据：节奏上有点透支**` ⇒ 取值成 `节奏上有点透支**`
                #     ⇒ ★ **逐字子串判红**（★ 明明是对的）。
                #   ★★ 而这条**不是改语义** —— ★ 因为**反引号包裹**（`` `思考位：…` ``）
                #     在本账里**早就工作正常**（★ 行里的 `位来源` 取到了 `层选` 等合法值）
                #     ⇒ ★ 剥 `**` 只是把**同一种包裹**也认了。
                #   ★★ **不剥中间、也不剥括号说明** —— ★ 后者牵涉「落款允不允许带说明」这个**口径**，
                #     ★ 故**留待持有方裁**（★ 实测 3 行因此判红）。
                out[key] = mm.group(1).strip().strip("*_").strip()

    # ★ 推论类型：只认落款那一行里的（§15.4 定义）
    mi = RE_ITYPE.search(text)
    if mi:
        out["inference_type_raw"] = mi.group(1).strip()
        out["inference_type"] = mi.group(1).strip() if mi.group(1).strip() in INFERENCE_TYPES else None

    if RE_F5_LINE.search(text) or ("不适用层位框架" in text):
        out["form"], out["f5_present"] = 5, True
        ms = RE_F5_SENT.search(text)
        if ms:
            out["f5_sentence"] = ms.group(1)
        for mm in RE_F5_QUAD.finditer(text):
            label, verdict, reason = mm.group(1), mm.group(2), mm.group(3)
            if label:
                out["f5_quad"][label] = {"verdict": verdict, "reason": (reason or "").strip()}
    elif "未过位" in text and "最小入口" in text:
        out["form"] = 4
    elif out["has_sig"]:
        out["form"] = 1          # 形态 1 / 2 / 3 在落款条款上同构（都要求 `层依据`）
        if out["layer"] and "判不明" in out["layer"]:
            out["form"] = 3
    return out


def layers_from(snippet: str) -> set:
    got = set()
    for L, kws in SIGNAL_KEYWORDS.items():
        if any(k in snippet for k in kws):
            got.add(L)
    return got


def _legacy_gate(ts, cutover):
    """True ⇒ 该轮**早于判据生效** ⇒ 记 uncomputable，不记红。
    None ⇒ **无时间戳**：判据适用性不可判（v3.6 fail-closed 的对象）。"""
    if not ts:
        return None
    if not cutover:
        return False
    try:
        return datetime.strptime(ts.strip(), "%Y-%m-%d %H:%M:%S") < datetime.strptime(cutover.strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


# ------------------------------------------------------------------ 单轮判定
#: ★★★ 「**本模块所用口径**」的指纹（v3.7 加 · 步 4 的症结）。
#:   ★ 为什么算在**底**：口径的定义在这里（"PROFILE_ID / REPEAT_THRESHOLD / LAYER_EVIDENCE_MAX /
#:     SIGNAL_TABLE_SHA / cutover" 全是本模块常量）⇒ ★ 放别处就是**第二份定义**。
#:   ★ 它解的是 C 指出的陷阱：**指纹若在记账当刻算，一轮横跨两版口径就会记错**。
#:   ★ 现在改为：**判当刻算、由判者自己返回** ⇒ ★ 它回答的是「**这一轮到底被哪版口径判过**」。
def criteria_hash() -> str:
    parts = [
        "profile=" + str(PROFILE_ID),
        "repeat=" + str(REPEAT_THRESHOLD),
        "ev_max=" + str(LAYER_EVIDENCE_MAX),
        "form5_max=" + str(FORM5_SENTENCE_MAX),
        "sig=" + str(SIGNAL_TABLE_SHA)[:16],
        "cutover=" + str(DEFAULT_CUTOVER),
        "v36=" + str(V36_CUTOVER),
        "inf_cutover=" + str(INFERENCE_CUTOVER),
        "source_enum=" + "/".join(SOURCE_ENUM),
        "inf_types=" + "/".join(INFERENCE_TYPES),
        "layer_order=" + "/".join(LAYER_ORDER),
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


#: ★★★ 「不算本模型的输出」的**可执行定义**（v3.7 加 · 2026-10-08 · 依设计 A/决定单「丙·分层」）。
#:   ★ 正本有 4 处散文这么宣称（`:363` §8.1 · `:424` §8.5 · `:592` §十三 · `:745` §13.4 表），
#:     而**机制里零实现** ⇒ ★ 本常量把它变成**一个可机检的整轮定性**。
#:   ★★ **而有一处做不到，这里必须写明**：`:363`（§8.1 层判错，"材料所见信号 ≠ 用户指定层"）
#:     ★ **底判不了它** —— 因为"材料所见信号"**没有可执行定义** ⇒ ★ 那一处**如实降级措辞**（归正本作者）。
#:   ★★ **另一条硬约束（架构）**：★ 服务是**流式**，回答**先发出去**、判据后跑
#:     ⇒ ★ **"不算输出"只能落成"事后如实标记"，落不成"抹掉那一轮"**。
NOT_OUTPUT_CRITERIA = ("source_present", "layer_evidence_present")


def judge_round(text: str, material: str = "", ts=None, cutover=DEFAULT_CUTOVER,
                assume_era_missing_ts: bool = True) -> dict:
    """★ 包装：调原实现，并**强制回填**两样 —— ① 判当刻的口径指纹；② 整轮的「算不算输出」定性。

    ★ 为何用包装而不逐个改 5 处 `return`：★ 那五处分散在不同分支
      ⇒ ★ **漏一处就会让那一档的账没有指纹**，而那**不会报错**。
    """
    out = _judge_round_impl(text, material=material, ts=ts, cutover=cutover,
                            assume_era_missing_ts=assume_era_missing_ts)
    if isinstance(out, dict):
        out["criteria_hash"] = criteria_hash()
        # ★★★ 整轮定性：★ `NOT_OUTPUT_CRITERIA` 里**任一为 red** ⇒ 该轮 `not_output = True`
        #   ★ 依据：★ §8.5 / §十三 那句「落款缺"位来源"或缺"层依据" ⇒ **该轮不算本模型的输出**」。
        #   ★ 为何用**整轮字段**而不是再加一条判据：★ `red` **已经在 findings 里了**；
        #     这里补的是**一个跨越单条判据的结论**（★ 那正是"不算输出"的信息量所在）。
        #   ★ 判据语义边界：★ **只在"有落款形态可判"时成立** —— ★ 形态 4/无落款时
        #     `layer_evidence_present` / `source_present` 不适用（`uncomputable`）⇒ ★ 不据此判"非输出"。
        _red = {f.get("name") for f in (out.get("findings") or [])
                if f.get("verdict") == "red"}
        _hit = sorted(_red & set(NOT_OUTPUT_CRITERIA))
        out["not_output"] = bool(_hit)
        out["not_output_why"] = (
            "★ 落款缺「位来源」或缺「层依据」⇒ 依 §8.5 / §十三，**该轮不算本模型的输出**"
            "（触发：" + " + ".join(_hit) + "）" if _hit else "")
    return out


def _judge_round_impl(text: str, material: str = "", ts=None, cutover=DEFAULT_CUTOVER,
                assume_era_missing_ts: bool = True) -> dict:
    sig = parse_signature(text)
    body = strip_signature(text)
    hay = (material or "") + "\n" + body
    findings = []

    def add(name, verdict, detail="", kind=None):
        f = {"name": name, "verdict": verdict, "detail": detail}
        if kind:
            f["kind"] = kind
        findings.append(f)

    form = sig["form"]
    legacy = _legacy_gate(ts, cutover)
    if legacy is None and assume_era_missing_ts:
        legacy = False          # --text 单轮校验：人主动发起的核验，无 ts ⇒ 按 v3.5 时代处理（§13.4 适用性口径）

    if form is None or form == 4:
        return {"form": form, "findings": findings, "norm": None,
                "note": "无落款 / 形态4（最小入口档）：§13.4 落款判据不适用（★ 但「没走位」本身是数据）"}

    if legacy is None:
        # ★ v3.6 fail-closed：无时间戳 ⇒ 判据适用性不可判 ⇒ 全部 uncomputable，**不许记红**
        INF3 = ("inference_type_present", "inference_type_backed", "inference_type_no_inflation")
        names = (("form5_evidence_present", "form5_quad_check", "form5_reason_nonempty") if form == 5 else
                 ("layer_evidence_present", "layer_evidence_len", "layer_evidence_verbatim",
                  "layer_vs_evidence", "source_present")) + INF3
        for n in names:
            add(n, "uncomputable", "无时间戳 ⇒ 判据适用性不可判（fail-closed，v3.6）")
        return {"form": form, "findings": findings, "norm": None,
                "note": "无 ts（fail-closed）：把「不知道」渲染成红就是做假读数"}

    if form == 5:
        if legacy:
            for n in ("form5_evidence_present", "form5_quad_check", "form5_reason_nonempty"):
                add(n, "uncomputable", "判据晚于账（该轮落款早于 v3.5，未含该形态的硬判据字段）")
            return {"form": 5, "findings": findings, "norm": None,
                    "note": "形态5（存量轮）：逐字句 / 四类标注 / 理由 三项皆是 v3.5 新要求 ⇒ 记不可核"}
        # ① 出示被检查的句子
        s = sig["f5_sentence"]
        if not sig["f5_present"] or s is None or not s.strip():
            add("form5_evidence_present", "red", "缺 `句「…」`（不得只写「未命中」）")
        elif len(s.strip()) > FORM5_SENTENCE_MAX:
            add("form5_evidence_present", "red", "被检查句 > {0} 字（{1} 字）".format(FORM5_SENTENCE_MAX, len(s.strip())))
        elif not hay.strip():
            add("form5_evidence_present", "uncomputable", "材料与正文皆不可得 ⇒ 逐字子串无法核")
        elif s.strip() not in hay and s.strip() not in text:
            add("form5_evidence_present", "red", "被检查句**不是**材料/输入的逐字子串：{0!r}".format(s.strip()[:40]))
        else:
            add("form5_evidence_present", "green", "句逐字可核（{0} 字）".format(len(s.strip())))
        # ② 四类信号逐类标注
        missing = [L + "层" for L in LAYER_ORDER if (L + "层") not in sig["f5_quad"]]
        if missing:
            add("form5_quad_check", "red", "未逐类标注：缺 {0}".format(" · ".join(missing)))
        else:
            add("form5_quad_check", "green", "四类（明/时/事/己）均已逐类标注")
        # ③ 未命中旁理由不得为空
        blanks = [L + "层" for L, v in sig["f5_quad"].items() if v["verdict"] == "未命中" and not v["reason"]]
        if blanks:
            add("form5_reason_nonempty", "red", "「未命中」旁理由为空：{0}".format(" · ".join(blanks)))
        else:
            add("form5_reason_nonempty", "green", "各「未命中」均带理由")
        return {"form": 5, "findings": findings, "norm": None,
                "note": "形态5：落款判据 = 出示被检查句 + 四类逐类标注 + 理由非空"}

    # ---- 形态 1 / 2 / 3：`层依据` 为必填
    ev = sig["evidence"]
    if legacy:
        add("layer_evidence_present", "uncomputable", "判据晚于账（该轮落款早于 v3.5，无 `层依据` 字段）")
    elif not sig["has_evidence_field"]:
        add("layer_evidence_present", "red", "落款缺 `层依据：`")
    elif ev is None or ev.strip() in EMPTY_EVIDENCE:
        add("layer_evidence_present", "red", "`层依据` 为空 / 为「无」 / 为「综合判断」（{0!r}）".format((ev or "").strip()[:20]))
    else:
        add("layer_evidence_present", "green", "有非空 `层依据`")

    ev_ok = bool(ev) and ev.strip() not in EMPTY_EVIDENCE

    # 长度
    if ev_ok:
        n = len(ev.strip())
        add("layer_evidence_len", "green" if n <= LAYER_EVIDENCE_MAX else "red",
            "片段 {0} 字（上限 {1}）".format(n, LAYER_EVIDENCE_MAX))

    # 逐字
    if ev_ok:
        if not hay.strip():
            add("layer_evidence_verbatim", "uncomputable", "材料与正文皆不可得 ⇒ 逐字子串无法核")
        elif ev.strip() in hay:
            add("layer_evidence_verbatim", "green", "片段是材料/正文的逐字子串")
        else:
            add("layer_evidence_verbatim", "red", "片段**不是**逐字子串：{0!r}".format(ev.strip()[:40]))

    # 层 vs 依据（★ v3.6：推定标记 `*` 剥掉后再比对——`*` 不得使层比对落空）
    if ev_ok and sig["layer"] and "判不明" not in sig["layer"]:
        derived = layers_from(ev)
        toks = [x.rstrip("*").strip() for x in re.split(r"[+＋、,，/]", sig["layer"])]
        written = set(x for x in toks if x in LAYER_ORDER)
        if not derived:
            add("layer_vs_evidence", "red",
                "map_miss：片段不含映射表任何关键词 ⇒ 层推不出（写的是 {0}；★ 这是映射表的失效信号，不是模型乱判层）".format(sig["layer"]),
                kind="map_miss")
        elif written and not written <= derived:
            add("layer_vs_evidence", "red",
                "layer_mismatch：层 {0} 超出片段推出的层集 {1}".format("+".join(sorted(written)), "+".join(sorted(derived)) or "∅"),
                kind="layer_mismatch")
        else:
            add("layer_vs_evidence", "green", "层 {0} ⊂ 片段推出的 {1}".format(sig["layer"], "+".join(sorted(derived))))

    # ★ v3.6 第 9 条：source_present（§13「缺位来源 ⇒ 该轮不算输出」的机检化）
    if not legacy:
        src_raw = (sig["source"] or "").strip()
        # ★★ v3.8：**容忍"值 + 明确开括号说明"**（★ 持有方裁：落款允许带说明）。
        #   ★ 实测三行本意合规而被判红（`指定（用户明示覆盖路径）` 等）⇒ ★ 见 `_enum_value` 的说明。
        src, src_gloss = _enum_value(src_raw, SOURCE_ENUM)
        if src in SOURCE_ENUM:
            if src_gloss:
                add("source_present", "green",
                    "位来源 = {0}（三值枚举内；★ 说明性后缀已归一化：{1!r}）".format(src, src_gloss[:40]))
            else:
                add("source_present", "green", "位来源 = {0}（三值枚举内）".format(src))
        else:
            add("source_present", "red",
                "缺 `位来源：` 或值不在三值枚举（层选/指定/兜底）内：{0!r}".format(src_raw or "（无）"))

    # ★★ v3.7 §15.5 三条推论判据（本轮新增）
    #   ★ 它们**不在** `legacy`（v3.5）口径内，而在自己的 INFERENCE_CUTOVER 之后生效；
    #     因为旧轮次从未写过这一栏 ⇒ 拿它们去判旧轮就是假红。
    it_cut = _legacy_gate(ts, INFERENCE_CUTOVER)
    if it_cut is None:
        for nm in ("inference_type_present", "inference_type_backed", "inference_type_no_inflation"):
            add(nm, "uncomputable", "无时间戳 ⇒ 推论判据适用性不可判（fail-closed）")
    elif it_cut:
        for nm in ("inference_type_present", "inference_type_backed", "inference_type_no_inflation"):
            add(nm, "uncomputable", "该轮早于推论判据生效时刻（{0}）⇒ 该栏当时不存在".format(INFERENCE_CUTOVER))
    else:
        declared_raw = sig["inference_type_raw"]
        declared = sig["inference_type"]
        did_infer = bool(RE_IFTHEN.search(body))
        # ① present：做了推演而落款无 `推论类型`
        if did_infer and not declared_raw:
            add("inference_type_present", "red",
                "正文含「若…则…」结构（做了推演）而落款无 `推论类型`（§15.4）")
        elif declared_raw and declared is None:
            add("inference_type_present", "red",
                "`推论类型` 值不在五类枚举内：{0!r}".format(declared_raw[:24]))
        else:
            add("inference_type_present", "green",
                "做推演则有该栏，且值在五类内" if declared_raw else "未做推演 ⇒ 本栏不适用（合规）")
        # ② backed：写了类型名 ⇒ 正文须可指认「起点」与「返回路径」
        if declared_raw:
            miss = []
            if not RE_PREMISE.search(body): miss.append("起点")
            if not RE_RETURN.search(body): miss.append("返回路径")
            if miss:
                add("inference_type_backed", "red",
                    "写了类型名而正文无可指认的：{0}".format(" · ".join(miss)))
            else:
                add("inference_type_backed", "green", "类型名 + 起点 + 返回路径 三者齐")
        # ③ no_inflation：未做推演却写了该栏
        if declared_raw and not did_infer:
            add("inference_type_no_inflation", "red",
                "未做推演（正文无「若…则…」）而写了 `推论类型` ⇒ 落款通胀（§15.5）")
        else:
            add("inference_type_no_inflation", "green", "无落款通胀")

    norm = normalize(ev) if ev_ok else None
    return {"form": form, "findings": findings, "norm": norm, "evidence": ev}


# ------------------------------------------------------------------ 批量（加跨轮重复）
def judge_batch(rounds, cutover=DEFAULT_CUTOVER, assume_era_missing_ts: bool = True) -> dict:
    """rounds: [{"text":…, "material":…, "ts":…}] ；返回含 `same_layer_evidence_repeat` 的判定。
    ★ v3.6：**账面扫描路径（scan）传 assume_era_missing_ts=False** ⇒ 无 ts 的轮 fail-closed 记 uncomputable；
    --text 单轮保持默认 True（人主动核验）。"""
    per = [judge_round(r.get("text", ""), r.get("material", ""), r.get("ts"), cutover,
                       assume_era_missing_ts=assume_era_missing_ts) for r in rounds]

    buckets = {}
    for i, p in enumerate(per):
        if p["norm"]:
            buckets.setdefault(p["norm"], []).append(i)

    repeats = {k: v for k, v in buckets.items() if len(v) >= REPEAT_THRESHOLD}
    for i, p in enumerate(per):
        if p["form"] in (None, 4, 5):
            continue
        if p["norm"] is None:
            p["findings"].append({"name": "same_layer_evidence_repeat", "verdict": "uncomputable",
                                  "detail": "无 `层依据` ⇒ 本判据没有对象"})
        elif p["norm"] in repeats:
            p["findings"].append({"name": "same_layer_evidence_repeat", "verdict": "red",
                                  "detail": "同一片段（归一化后）出现 {0} 轮 ≥ 阈值 {1}；★ 命中≠有问题，只触发人看".format(len(buckets[p["norm"]]), REPEAT_THRESHOLD)})
        else:
            p["findings"].append({"name": "same_layer_evidence_repeat", "verdict": "green",
                                  "detail": "出现 {0} 轮 < 阈值 {1}".format(len(buckets.get(p["norm"], [])), REPEAT_THRESHOLD)})
    return {"rounds": per, "repeat_groups": repeats, "repeat_group_count": len(repeats),
            "repeat_red_rounds": sum(1 for p in per if any(
                f["name"] == "same_layer_evidence_repeat" and f["verdict"] == "red" for f in p["findings"])),
            "echo": {"normalized_by": PROFILE_ID, "repeat_threshold": REPEAT_THRESHOLD,
                     "signal_table_sha256": SIGNAL_TABLE_SHA, "cutover": cutover}}


# ------------------------------------------------------------------ 验收
def selftest() -> int:
    print("=== §13.4 落款判据 · 验收（3 负例 + 1 正例 + v3.6 新增 2 负例）===")
    print("口径回显：normalized_by={0} · repeat_threshold={1} · 映射表指纹={2} · cutover={3} · 判据版本=v3.6".format(
        PROFILE_ID, REPEAT_THRESHOLD, SIGNAL_TABLE_SHA[:16], DEFAULT_CUTOVER))
    ok = 0
    total = 0

    def verdicts(batch, i):
        return {f["name"]: f["verdict"] for f in batch["rounds"][i]["findings"]}

    # 负例 1：`层依据` 写「无」
    t1 = "你把这件事的先后排一下。\n\n思考位：M3 M4 A3（层依据：「无」 · 层:事* · 位来源：层选 · 自检：未触发 · 锚：3/3）\n\n显化声明：本回答是显化，不是根。根不在本回答中。"
    b1 = judge_batch([{"text": t1, "material": "我手头事排不开，先做哪个？", "ts": "2026-10-06 13:00:00"}])
    total += 1
    got = verdicts(b1, 0).get("layer_evidence_present")
    good = got == "red"
    ok += good
    print("\n[负例1] 层依据写「无」→ layer_evidence_present = {0}  {1}".format(got, "PASS" if good else "FAIL"))

    # 负例 2：同一 `层依据` 片段连写 3 轮
    tpl = "……正文……\n\n思考位：M3 M4 A3（层依据：「排序/资源」 · 层:事* · 位来源：层选 · 自检：未触发 · 锚：3/3）"
    b2 = judge_batch([{"text": tpl, "material": "排序/资源 都卡住了", "ts": "2026-10-06 13:0{0}:00".format(i)} for i in range(3)])
    total += 1
    got = verdicts(b2, 0).get("same_layer_evidence_repeat")
    good = got == "red"
    ok += good
    print("[负例2] 同片段 3 轮 → same_layer_evidence_repeat = {0}  {1}".format(got, "PASS" if good else "FAIL"))

    # 负例 3：用第五形态但不写被检查句
    t3 = ("本问题不适用层位框架。\n\n"
          "形态5判定：明层:未命中（无「怎么看/是什么」） · 时层:未命中（无节奏） · 事层:未命中（无排序） · 己层:未命中（无边界）\n\n"
          "显化声明：本回答是显化，不是根。根不在本回答中。材料：无")
    b3 = judge_batch([{"text": t3, "material": "帮我起个名字", "ts": "2026-10-06 13:00:00"}])
    total += 1
    got = verdicts(b3, 0).get("form5_evidence_present")
    good = got == "red"
    ok += good
    print("[负例3] 第五形态不写被检查句 → form5_evidence_present = {0}  {1}".format(got, "PASS" if good else "FAIL"))

    # 正例：正常一轮（片段逐字、层与片段一致、未用第五形态）—— 必须**全绿、不误报**
    mat = "我手头几件事排不开：排序/资源 都卡着，不知道先推哪个。"
    t4 = ("先说结论：先排「资源」再谈「排序」。\n\n"
          "思考位：M3 M4 A3（层依据：「排序/资源」 · 层:事* · 位来源：层选 · 自检：未触发 · 锚：3/3）\n\n"
          "显化声明：本回答是显化，不是根。根不在本回答中。材料：长度 30 + 我手头几件事排不开…")
    b4 = judge_batch([{"text": t4, "material": mat, "ts": "2026-10-06 13:00:00"}])
    total += 1
    vs = verdicts(b4, 0)
    bad = {k: v for k, v in vs.items() if v == "red"}
    good = not bad
    ok += good
    print("[正例 ] 正常轮 → 全部 = {0}；红项 {1}  {2}".format(
        "/".join(sorted(set(vs.values()))), (bad or "无"), "PASS" if good else "FAIL"))
    if bad:
        for k, v in bad.items():
            print("        ↳ ", k)

    # 负例 4（v3.6 · 阻断①回归）：`层:明*` 带推定标记逃逸——依据推出"事"，写"明*"必须红
    t7 = ("……正文……\n\n思考位：M3 M4 A3（层依据：「排序/资源」 · 层:明* · 位来源：层选 · 自检：未触发 · 锚：3/3）")
    b7 = judge_batch([{"text": t7, "material": "排序/资源 都卡住了", "ts": "2026-10-06 13:00:00"}])
    total += 1
    got = verdicts(b7, 0).get("layer_vs_evidence")
    good = got == "red"
    ok += good
    print("[负例4] 层:明*（*逃逸回归）→ layer_vs_evidence = {0}  {1}".format(got, "PASS" if good else "FAIL"))

    # 负例 5（v3.6 · 阻断③）：缺 `位来源` ⇒ source_present 必红
    t8 = "……正文……\n\n思考位：M3 M4 A3（层依据：「排序/资源」 · 层:事 · 自检：未触发 · 锚：3/3）"
    b8 = judge_batch([{"text": t8, "material": "排序/资源 都卡住了", "ts": "2026-10-06 13:00:00"}])
    total += 1
    got = verdicts(b8, 0).get("source_present")
    good = got == "red"
    ok += good
    print("[负例5] 缺位来源 → source_present = {0}  {1}".format(got, "PASS" if good else "FAIL"))

    print("\n=== 结果：{0}/{1} 通过 ===".format(ok, total))

    # ---- 附加反向探针（不属 REQ 四条，但防"一律红"与"层不校验"两类假工具）
    print("\n--- 附加反向探针（防漏检 / 防一律红）---")
    p_ok = 0
    p_tot = 0
    # 探针 A：第五形态**写全**（句逐字 + 四类标注 + 理由）⇒ 应全绿
    mat5 = "帮我写一首关于秋天的诗，随便来两句就行"
    t5 = ("秋天如果要写，就先写风。\n\n"
          "形态5判定：句「帮我写一首关于秋天的诗」｜明层:未命中（问的是创作不是认知） · 时层:未命中（无关节奏） · "
          "事层:未命中（不是推进具体事） · 己层:未命中（不涉边界/坚持）\n\n"
          "显化声明：本回答是显化，不是根。根不在本回答中。材料：无")
    b5 = judge_batch([{"text": t5, "material": mat5, "ts": "2026-10-06 13:00:00"}])
    v5 = verdicts(b5, 0)
    p_tot += 1
    good = not any(v == "red" for v in v5.values())
    p_ok += good
    print("[探针A] 第五形态写全 → 红项 {0}  {1}".format(
        {k: v for k, v in v5.items() if v != "green"} or "无", "PASS" if good else "FAIL"))
    # 探针 B：层与依据不符（片段只含事层关键词，却写「层:明」）⇒ layer_vs_evidence 应红
    t6 = ("……正文……\n\n思考位：M3 M4 A3（层依据：「排序/资源」 · 层:明 · 位来源：层选 · 自检：未触发 · 锚：3/3）")
    b6 = judge_batch([{"text": t6, "material": "排序/资源 都卡住了", "ts": "2026-10-06 13:00:00"}])
    p_tot += 1
    got = verdicts(b6, 0).get("layer_vs_evidence")
    good = got == "red"
    p_ok += good
    print("[探针B] 层与依据不符 → layer_vs_evidence = {0}  {1}".format(got, "PASS" if good else "FAIL"))
    # 探针 C（v3.6 · 阻断②回归）：第 3 形态**按新限定写**（层依据=冲突信号词，逐字取自材料）⇒ 应全绿
    mat3 = "现在的问题：累了、排序 两头都紧——人乏了，事也没排出先后。"
    t9 = ("层判先搁置：时层与事层的信号在打架。\n\n"
          "思考位：M3 M4 A3（层依据：「累了、排序」 · 层:层判不明 · 位来源：层选 · 自检：未触发 · 锚：3/3）\n\n"
          "显化声明：本回答是显化，不是根。根不在本回答中。材料：无")
    b9 = judge_batch([{"text": t9, "material": mat3, "ts": "2026-10-06 13:00:00"}])
    v9 = verdicts(b9, 0)
    p_tot += 1
    bad9 = {k: v for k, v in v9.items() if v == "red"}
    good = not bad9
    p_ok += good
    print("[探针C] 形态3按限定写全 → 红项 {0}  {1}".format(bad9 or "无", "PASS" if good else "FAIL"))
    # 探针 D（v3.6 · 应修5回归）：账面轮**无时间戳** ⇒ 全 uncomputable，不许记红
    b10 = judge_batch([{"text": t6, "material": "排序/资源 都卡住了", "ts": None}], assume_era_missing_ts=False)
    v10 = verdicts(b10, 0)
    p_tot += 1
    good = v10 and all(v == "uncomputable" for v in v10.values())
    p_ok += good
    print("[探针D] 无ts（扫描路径）→ 全 uncomputable  {0}".format("PASS" if good else "FAIL " + str(v10)))
    print("--- 探针：{0}/{1} ---".format(p_ok, p_tot))
    return 0 if (ok == total and p_ok == p_tot) else 1


# ------------------------------------------------------------------ 扫会话侧
def scan(path: Path, cutover: str, as_json: bool) -> int:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rounds = []
    for s in data.get("sessions", []):
        last_user = ""
        for t in s.get("turns", []):
            if t.get("role") == "user":
                last_user = t.get("content", "")
            elif t.get("role") == "assistant":
                rounds.append({"text": t.get("content", ""), "material": last_user,
                               "ts": t.get("ts"), "session": s.get("title", "")})
    b = judge_batch(rounds, cutover, assume_era_missing_ts=False)   # ★ v3.6：账面扫描无 ts ⇒ fail-closed

    # ★ 版本划分**按时间划，不按内容猜**（按内容猜会把"v3.5 时代漏写层依据"误判成"存量"⇒ 漏报）
    f123 = f4 = f5 = none = pre = era = no_ts = 0
    for p, r in zip(b["rounds"], rounds):
        if p["form"] is None:
            none += 1
        elif p["form"] == 5:
            f5 += 1
        elif p["form"] == 4:
            f4 += 1
        else:
            f123 += 1
        if p["form"] is not None:
            g = _legacy_gate(r.get("ts"), cutover)
            if g is True:
                pre += 1
            elif g is None:
                no_ts += 1          # ★ v3.6：fail-closed 单列，不混进"时代内"
            else:
                era += 1
    judgeable = sum(1 for p in b["rounds"] if p["norm"])

    tally = {}
    kinds = {}
    for p in b["rounds"]:
        for f in p["findings"]:
            tally.setdefault(f["name"], {}).setdefault(f["verdict"], 0)
            tally[f["name"]][f["verdict"]] += 1
            if f.get("kind"):
                kinds.setdefault(f["name"], {}).setdefault(f["kind"], 0)
                kinds[f["name"]][f["kind"]] += 1

    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": str(path),
        "rounds_total": len(rounds),
        "echo": b["echo"],
        "signature_forms": {"形态1/2/3（走位轮）": f123, "形态4（最小入口）": f4,
                            "形态5（不适用档）": f5, "无落款": none},
        "judgeability": {"v3.5 时代（判据适用）": era, "v3.5 前（判据晚于账 ⇒ 不可核）": pre,
                         "无时间戳（v3.6 fail-closed ⇒ 不可核）": no_ts},
        "judgeable_evidence_rounds": judgeable,
        "judgement_tally": tally,
        "layer_vs_evidence_kinds": kinds.get("layer_vs_evidence", {}),
        "repeat_red_rounds": b["repeat_red_rounds"],
        "normalized_snippet_groups": b["repeat_group_count"],
    }
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print("=== 落款校验 · 会话侧扫描 ===")
    print("源：{0}".format(path))
    print("口径回显：normalized_by={0}".format(b["echo"]["normalized_by"]))
    print("          repeat_threshold={0} · 映射表指纹={1}".format(
        b["echo"]["repeat_threshold"], b["echo"]["signal_table_sha256"][:16]))
    print("          cutover（判据生效时刻）={0}".format(b["echo"]["cutover"]))
    print("助手轮总数：{0}".format(len(rounds)))
    print("落款形态分布：")
    for k, v in result["signature_forms"].items():
        print("   {0:<28} {1}".format(k, v))
    print("判据适用性（★ 按时间划，不按内容猜）：")
    for k, v in result["judgeability"].items():
        print("   {0:<30} {1}".format(k, v))
    print("\n判据命中（红 / 绿 / 不可核）：")
    for name, d in sorted(tally.items()):
        extra = ""
        if name == "layer_vs_evidence" and kinds.get(name):
            extra = "\n      ★ v3.6 分栏：map_miss={0} · layer_mismatch={1}".format(
                kinds[name].get("map_miss", 0), kinds[name].get("layer_mismatch", 0))
        print("   {0:<30} 红={1:<4} 绿={2:<4} uncomputable={3}{4}".format(
            name, d.get("red", 0), d.get("green", 0), d.get("uncomputable", 0), extra))
    print("\n★ 空转（same_layer_evidence_repeat）：")
    if judgeable == 0:
        print("   可判轮数 = 0 ⇒ **无读数（uncomputable）**")
        print("   ★ 原因：会话侧有 `层依据` 的轮 = 0（存量落款早于 v3.5）⇒ 判据没有对象。")
        print("   ★ 这不是「零空转」，也不是「全空转」 —— 是**还没开始记**。")
    else:
        print("   可判轮数 = {0} · 同一片段分组 = {1} · 触发红 = {2} 轮".format(
            judgeable, b["repeat_group_count"], b["repeat_red_rounds"]))
        if judgeable < REPEAT_THRESHOLD:
            print("   ★ 读数**弱**：可判轮数 {0} < 阈值 {1} ⇒ 「空转率」此刻**不可度量**，"
                  "只能报「有没有出现重复」。".format(judgeable, REPEAT_THRESHOLD))
    print()
    return 0


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description="落款判据 · 可执行底（拆解器外发版）")
    ap.add_argument("--selftest", action="store_true", help="跑四条验收（3 负例 + 1 正例）")
    ap.add_argument("--scan", nargs="?", const=str(DEFAULT_SESSIONS), default=None,
                    help="扫会话侧 sessions.json")
    ap.add_argument("--text", help="校验单轮：正文文件")
    ap.add_argument("--material", default="", help="校验单轮：材料文件（可选）")
    ap.add_argument("--cutover", default=DEFAULT_CUTOVER, help="判据生效时刻（此前记 uncomputable）")
    ap.add_argument("--json", action="store_true", help="机器可读")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.scan:
        return scan(Path(args.scan), args.cutover, args.json)
    if args.text:
        text = Path(args.text).read_text(encoding="utf-8")
        material = Path(args.material).read_text(encoding="utf-8") if args.material else ""
        b = judge_batch([{"text": text, "material": material}], args.cutover)
        print(json.dumps(b["rounds"][0], ensure_ascii=False, indent=2))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
