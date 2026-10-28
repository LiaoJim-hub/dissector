#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""loop · 根式核心回路（★ 层位提示 · 回流 · 模型调用）

★★★ 为什么有这一个文件（★ 2026-10-09 实测）：
   ★ 原先这三件事**写在 `server.py` 里**，★ 而那个文件第 31 行就是 `import httpx`。
   ⇒ ★★ **只想用那 86 行的回流，也得装 fastapi / uvicorn / httpx / pydantic。**
   ★★★ 故本模块把它们拆出来，★ **零第三方依赖** —— ★ 业务方可以只 import 它。

★ 依赖（★ 全部是本包内的，★ 且都可选）：
   · `session_log`          —— ★ 读账（判据读数从哪来）
   · `protocol/拆解器·协议.md` —— ★ 提示词的**正文**（★ 层位定义写在它里面）
   · `protocol/POSITIONS.md`   —— ★★ **本模块不读它** —— ★ 实测它**从不进提示词**（见 spec/验收件）

★ 三个注入点（★ 不注入也能跑，★ 只是会少一两段）：
   · `const_block`   —— ★ §5.3 常量块闸的读数（缺 ⇒ 明写"无法判"，★ 不当作通过）
   · `search_cfg`    —— ★ 检索工具配置（缺 ⇒ 不下发检索）
   · `can_read_fs`   —— ★ 可读根是否生效（缺 ⇒ 不下发读文件纪律）

★ 依两件协议 §3，本模块不产生判定主体。
"""
from __future__ import annotations

import pathlib
import re

APP_DIR = pathlib.Path(__file__).resolve().parent
# ★ 2026-10-13 修（★ 敌手D 第10轮 V-4 同批）：★ 原文件名在包里**不存在**（包里只有拆解器·协议.md）
#   ⇒ 此前这个回退路径**永远落空**；★ 现指向真件（★ `loop.py:153` 的 `pf = protocol_file or PROTOCOL_FILE`）。
PROTOCOL_FILE = APP_DIR / "protocol" / "拆解器·协议.md"
POSITIONS_FILE = APP_DIR / "protocol" / "POSITIONS.md"   # ★ 定义在此**仅作路径参考**（★ 不进提示词）


# ══════════════════════════════════════════════════════════════════
# 一 · 不可核的**分类**（★ 零依赖 —— 实测 0 个模块级名字）
# ══════════════════════════════════════════════════════════════════
def classify_uncomputable(raw: str) -> str:
    """★ 把"不可核"的**理由**分成两类（★ 因为两类该被不同处置）。

    ★ 甲 = 底自己说「早于…生效时刻」      ⇒ **无需处置**（历史轮，判据当时还不存在）
    ★ 乙 = 底说「无时间戳 / fail-closed」 ⇒ **补上输入即可判**（判得了就不是不可核）
    ★★ 回显若标「待核」⇒ **不替它猜**。
    """
    s = str(raw or "")
    if re.search(r"(早于|之前|当时还不存在|未生效|生效时刻)", s):
        return "★ 甲 · 历史轮（判据当时尚未生效）⇒ 无需处置"
    if re.search(r"(无时间戳|时间戳缺失|fail.?closed|缺时间)", s):
        return "★ 乙 · 缺输入 ⇒ **补上即可判**（判得了就不是不可核）"
    return "★ 待核 —— **不要替它猜**，去判据底核该条"


# ══════════════════════════════════════════════════════════════════
# 二 · 回流（★ 核心四件的第 ④ 件 —— 本模块最要紧的一段）
# ══════════════════════════════════════════════════════════════════
def last_round_feedback(session_id: str = "", rows=None) -> str:
    """★ 读账里**本会话最后一轮**的判据读数；红与不可核**分栏**，并**标明来源**。

    ★★★ 三条防滥用（★ 照抄原实现，★ 一个字都没改）：
      ① **来源显形**：会话前 8 位 + 轮次；**跨会话回退时明说**（不再静默）。
      ② **红与不可核都回**（不可核只报名字，不占篇幅）。
      ③ **明写"这是已压缩的摘要 ⇒ 不许只读它就下判断"**。

    ★ 参数 `rows`：账行列表（缺 ⇒ 自己去 `session_log` 取）。
    """
    if rows is None:
        try:
            import session_log as _sl
            rows = _sl._rows()
        except Exception:                                        # noqa: BLE001
            return ""
    if not rows:
        return ""
    cur = [r for r in rows if session_id and r.get("session") == session_id]
    if cur:
        last = cur[-1]
        src = "本会话第 {0} 条账".format(len(cur))
        crossed = False
    else:
        # ★★ 本会话还没有账行（回显发生在本轮落账之前）⇒ 取全账最后一行，但【明说跨了】。
        last = rows[-1]
        src = "★ **不是本会话** —— 本会话尚无账行，此处取的是**全账最后一条**"
        crossed = True
    detail = last.get("judgement_detail") or []
    reds = [f for f in detail if f.get("verdict") == "red"]
    unc = [f for f in detail if f.get("verdict") == "uncomputable"]
    if not reds and not unc:
        return ""
    sid = str(last.get("session") or "?")[:8]
    tno = last.get("turn_no")
    ts = str(last.get("ts") or "")[:19]
    lines = ["", "# 上一轮判据读数（★ 系统实测，**非你自报**）"]
    lines.append("★ 以下由服务端跑判据底得出，**不是你的自评**；不得改写、不得当成你自己的判断复述。")
    lines.append("- **来源**：会话 `{0}…` · 轮 `{1}` · ts `{2}` · {3}".format(sid, tno, ts, src))
    if crossed:
        lines.append("  ★★ **故下面这些红/不可核，很可能【不是你这一轮的】** —— "
                     "引它们之前先核 session/轮次，**不要当成自己的上一轮**。")
    if reds:
        lines.append("## 红（{0} 条）".format(len(reds)))
        for f in reds[:4]:
            kd = f.get("kind")
            lines.append("- `{0}`{1} — {2}".format(
                f.get("name"), (" [{0}]".format(kd) if kd else ""), (f.get("detail") or "")[:120]))
    if unc:
        lines.append("## 不可核（{0} 条 · ★ **不可核 ≠ 通过**，但它也**不是红**）".format(len(unc)))
        for f in unc[:6]:
            kd = f.get("kind")
            lines.append("- `{0}`{1} — **{2}**".format(
                f.get("name"), (" [{0}]".format(kd) if kd else ""),
                classify_uncomputable(str(f.get("detail") or ""))))
        lines.append("  ★ **分栏依据**：甲 = 底自己说「早于…生效时刻」⇒ **无需处置**；"
                     "乙 = 底说「无时间戳 / fail-closed」⇒ **补上输入即可判**（★ 判得了就不是不可核）。"
                     "★ 回显若标「待核」⇒ **不要替它猜**，去判据底核该条。")
    lines.append("⇒ 本轮若再写落款，**针对上面这些**避免重犯；★ 但**不要为消红而凑格式**。")
    lines.append("★★ **另一件事必须做**：★ **不要只读这一行摘要就下判断** —— "
                 "它是**上一轮**的、且**已被压缩**。要论「我上一轮哪条错了、为什么」，"
                 "**去账里读该轮的 `judgement_detail` 原文**。")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 三 · 层位提示（★ 核心四件的第 ① 件）
# ══════════════════════════════════════════════════════════════════
def build_system_prompt(mode: str, protector: bool, session_id: str = "",
                        *, const_block=None, search_cfg=None, can_read_fs=None,
                        protocol_file: pathlib.Path | None = None,
                        protocol_text: str | None = None,
                        extra_sections: list | None = None,
                        rows=None,
                        return_breakdown: bool = False):
    """★ 拼 system prompt：**协议正文** + 本次会话参数 + 常量块闸读数 + **上一轮读数（回流）**。

    ★★ 三个注入点都是可选的：★ 不注入 ⇒ 相应那一段**明写"无法判"或缺省**，
        ★★ **不静默假装通过**（★ 这是本体系贯穿的一条）。

    ★★★ 业务接缝（★ 2026-10-09 加 · ★ 依 C 的《规格·DSH接缝 v0.1》那一层）：
       · `protocol_text`  —— ★ **直接用一段文本当协议正文**（★ 业务方不必先把它落成文件）。
          ★★ 传了它 ⇒ 优先于 `protocol_file`。★ **这是"换掉协议就换掉产品"那个机制的接口形态。**
       · `extra_sections` —— ★ 业务方追加的段落（★ 列表，逐项入 prompt）。
          ★★ **用途**：业务自己的场景纪律（★ 如"本场景不许开新话题"）。
          ★★ **而它有一个硬约束**：★ 追加段落**不得删改核心的判据段与回流段** ——
             ★ 本函数把 `extra_sections` 插在**参数段之后、常量块闸之前**，
             ★ 且**在最后才拼回流** ⇒ ★ **业务插不进来、也盖不掉回流。**

    ★★★ `return_breakdown=True`（★ 2026-10-09 本项目加 · ★ 记忆机制的落点一）：
       ⇒ ★ 返回 `(prompt, breakdown)`，★ `breakdown` = `[(段名, 字符数), …]`。
       ★★ **为什么要有它**（★ 出处：★ 方案·顾问记忆机制 §5.2 那条"没有读数的预算就是下一个
          「看起来正常」"）：★ 本函数**逐段 `parts.append`** ⇒ ★ 每段的长度**本来就现成**，
          ★ 而此前**没有任何一处把它量出来** ⇒ ★ **约束涨了也没人知道。**
       ★ **纪律**：★ 它是**只读的观测** —— ★ **不改任何一段的内容或顺序**（★ 顺序恒为
          「追加段 < 常量块闸 < 回流」，★ 见 `spec\接缝契约 v0.1` C3/C8）。
"""
    if protocol_text is not None:
        base = protocol_text
    else:
        pf = protocol_file or PROTOCOL_FILE
        base = pf.read_text(encoding="utf-8")
    parts = [base, "", "# 本次会话参数（用户在界面选择，优先级高于上文默认）"]
    # ★★ 分段量长（★ 只读观测 —— ★ 不改内容、不改顺序）
    _marks = [("L0·协议正文", len("\n".join(parts)))]
    # ★★★★ 2026-10-12 改：**恢复"工作模式"那一支 = 双档**（★ 出处：持有方判 + A 的《判断·护根该不该是唯一档位》）
    #   ★ 原先这里判的是：★ **删掉两个分支** ⇒ ★ 护根**恒定开**、★ 错传当场炸。
    #   ★★ 而依据（★ 内部件《装载件》:503–510 · ★ 外发包不含它，口径以本注释所引为准）：
    #     `:503` 根锚点三条（★ **护根模式的**完整立场）：
    #     `:507` - **工作模式（默认）**：不整体启用三条锚点（★ **否则无法干活**）——用户要答案就给答案。
    #     `:509` - **护根模式**（用户说出「进入护根模式」）：整体切换——只描述、只给路、只看见，不给答案。
    #     `:510` - 这三条不因互动多而松动…★ **若因「用户强烈要求」而开始给答案，那不是成长，是漂移。**
    #     ⇒ ★★ **`:510` 管的是护根模式开着的时候**（★ 抬头就是 `:503`）——
    #       ★ 而本版原先把 `:510` 当成了**整个产品的通用禁令** ⇒ **在工作模式该答的场合也拒绝给答案**。
    #   ★★★ 故：★ **`mode` 仍锁在 `"light"`**（★ 一行不改）；★ **`protector` 放开** ⇒ ★ **恢复源头那两行**
    #     （★ 逐字取自 `core\loop.py:169–174` · ★ **没有新造一个措辞**）。
    #   ★★★★ 而"护根只能由用户**显式**开"这条**没有被放松**：★ `ChatIn.protector` **默认 `False`**。
    if mode != "light":
        raise ValueError(
            "★ 本外发版只有轻档（mode={0!r}）—— ★ 调用方必须传 light".format(mode))
    parts.append("- 力度：**轻档**。选位与 M4/A3 校验在内部走完，正文自然流畅，"
                 "仅在末尾附一行思考位摘要 + 显化声明。")
    if protector:
        parts.append("- **护根模式已开启**：只描述、不评价；只给路、不给答案；只看见、不解释。"
                     "不回答「该不该」类问题，一切结论归还给人。")
    else:
        parts.append("- 工作模式（默认）：正常给答案、能干活；"
                     "仅对「人的状态」做辨认时只描述不评价。")

    # ★★ 业务追加段（★ 接缝注入点四 —— ★ 插在参数之后、常量块闸之前）
    #   ★★ 位置是**有意的**：★ 它进得来，★ 但**盖不掉**后面的常量块闸与回流。
    if extra_sections:
        parts.append("")
        parts.append("# 本场景追加纪律（★ 由业务 harness 注入）")
        for s in extra_sections:
            parts.append("- {0}".format(str(s).strip()))
    _marks.append(("L0·会话参数+追加段", len("\n".join(parts))))

    # ★★★★★ 2026-10-13：★ **未配检索那一段整块删**（★ 见本脚本 ⑤a-5 的注释）。
    #   ★ 协议铁律：★ `@@@FOOTER@@@` **必须恒为最后一段** —— ★ 而这一段原先排在落款之后
    #     ⇒ ★ 实测**落款之后还有 418 字符** ⇒ ★ 违反"最后一眼"。
    #   ★★ 而**删它没有松掉任何约束**：★ `if search_cfg:` 那一支留着，只是本版**无人传它**。
    if search_cfg:
        parts.append("")
        parts.append("# 检索")
        parts.append("- 已配检索工具；★ 用不用由你判断，★ 而**每次调用都会留痕**。")
    _marks.append(("L0·检索段", len("\n".join(parts))))

    # ★★★ 本外发版：★ **§5.3 常量块闸那一段已整块删**（★ 连同它的 `_marks` 读数行）。
    #   ★ 实测：★ 它**每轮都在提示词里**（★ 原版是**无条件**追加 —— 不传 `const_block` 也照样写），
    #     ★ 而它说的是「§5.2 常量块 / 退路作废 / 只许走 §5.1 调 CLI」
    #     ★★ —— ★ 那是**那份 91 KB 协议里的机制**，★ 本外发版**根本没有它**。
    #   ★★ 留着有两个坏处：★ ① 白占 145 字符；★ ② **模型会读到一套不存在的规矩**
    #     （★「提示词里写着不存在的东西」正是本体系一路在打的那个病）。
    #   ★★★ 而**删它没有松掉任何约束**：★ `const_block` 仍在函数签名里（★ 接口不变），
    #     ★ 只是本版**没有任何来源**会传它 ⇒ ★ 那一段**本来就不可能是有内容的**。

    # ★ 读文件纪律（★ 注入点三）
    if can_read_fs:
        parts.append("")
        parts.append("# 读本地文件")
        parts.append("- 已授权可读根 ⇒ **每次读都会留痕**（含被拒）。")

    # ★★★ 回流（★ 核心四件的第 ④ 件）
    fb = last_round_feedback(session_id, rows=rows)
    if fb:
        parts.append(fb)
    _marks.append(("L1·回流", len("\n".join(parts))))
    prompt = "\n".join(parts)

    if return_breakdown:
        # ★★ 由累计位置差算每段长度（★ 含 `""` 分隔造成的换行，★ 故各段之和恰等于总长）
        bd = []
        prev = 0
        for name, pos in _marks:
            bd.append((name, max(0, pos - prev)))
            prev = pos
        return prompt, bd
    return prompt


# ══════════════════════════════════════════════════════════════════
# ★★★ 上下文预算读数（★ 记忆机制的落点一 · ★ 2026-10-09 本项目加）
#
#   ★★★ 为什么有它（★ 出处：★ 方案·顾问记忆机制 §5.2）：
#      ★ 方案原话：★「**凡进约束的每一段，都必须在同一处打出一个可核读数** ——
#        ★ 段名 · ★ 字符数 · ★ 占预算百分比」· ★★「**没有读数的预算，就是下一个"看起来正常"**。」
#
#   ★★ 实测（★ 2026-10-09）给出的那条**方案里没有的事实**：
#      ★ `L0·协议正文 = 52,844 字符 = 总长的 99.5%` ⇒
#      ★★★ **可调的那六段（参数/检索/闸/回流/历史/文档）加起来不到 1%**
#      ⇒ ★ **故"预算表"的真问题不是"怎么分配"，★ 是「那 99.5% 能不能动」。**
#
#   ★ 纪律三条：
#      ① **只读** —— ★ 不改任何一段的内容、顺序、长度；
#      ② **可核** —— ★ `sum(段) == total`（★ 有断言，★ 见 `scripts\verify_all.py`）；
#      ③ **超限只报红，★ 不静默截断**（★ 与 `server.py` 里那条「不许截断后假装读到了」同立场）。
# ══════════════════════════════════════════════════════════════════
#: ★ 各段预算（★ **单位 = 字符** · ★ 值来自方案 §5.1 的更正版 · ★ 1 字符 ≈ 0.5–0.7 token，★ 不换算）
CONTEXT_BUDGET = {
    "L0·协议正文": 58000,
    "L0·会话参数+追加段": 2000,
    "L0·检索段": 300,
    "L0·常量块闸": 800,
    "L2·领域索引": 1600,
    "L2·检索正文": 2100,
    "L1·回流": 400,
    "L3·候选": 0,                 # ★★★ 结构保证：候选**不许进**
    "对话历史": 8000,
    "附带文档": 13000,
}
CONTEXT_BUDGET_TOTAL = 85000


def context_report(prompt: str = "", breakdown=None, *, history_chars: int = 0,
                   doc_chars: int = 0, extra: dict | None = None) -> dict:
    """★ 出**本轮约束的预算读数**（★ 逐段 · ★ 占比 · ★ 超没超）。

    ★ 参数：
       · `prompt`      —— ★ `build_system_prompt` 的返回值（★ 只用它算总长）
       · `breakdown`   —— ★ `build_system_prompt(..., return_breakdown=True)` 的第二项
       · `history_chars` / `doc_chars` —— ★ **本函数量不到的两段**（★ 它们在 `server.py` 里拼）
       · `extra`       —— ★ 其它要一起看的段（★ 如 `{"L2·领域索引": n}`）
    ★★ 返回：★ `{"段": [(名, 长度, 上限, 超没超)], "总": n, "上限": m, "超": [名…], "行": "一行读数"}`
    """
    segs: list = []
    if breakdown:
        segs.extend([(str(n), int(c)) for n, c in breakdown])
    if history_chars:
        segs.append(("对话历史", int(history_chars)))
    if doc_chars:
        segs.append(("附带文档", int(doc_chars)))
    for k, v in (extra or {}).items():
        segs.append((str(k), int(v)))

    # ★★★ 同名段**必须合并**（★ 实测教训 · 2026-10-09）：
    #   ★ breakdown 里已有一个 `L1·回流 = 0`（★ 无会话时），★ 而 `extra` 又传了真的回流长度
    #   ⇒ ★★ **不合并就会出现同名两行** ⇒ ★ 而**预算会被重复计** ⇒ ★ **读数就不可信**。
    #   ★ 合并方式 = **取最大值**（★ 同一段只能有一个真长度；★ 取最大是保守的）。
    _m: dict = {}
    for name, n in segs:
        if name in _m:
            _m[name] = max(_m[name], n)
        else:
            _m[name] = n
    segs = list(_m.items())

    out, 超 = [], []
    for name, n in segs:
        lim = CONTEXT_BUDGET.get(name)
        over = bool(lim is not None and n > lim)
        if over:
            超.append(name)
        out.append((name, n, lim, over))
    total = sum(n for _, n, _, _ in out)
    total = max(total, len(prompt or ""))
    超总 = total > CONTEXT_BUDGET_TOTAL
    行 = "约束 {0:,} / {1:,} ({2:.0f}%)".format(total, CONTEXT_BUDGET_TOTAL,
                                              100.0 * total / CONTEXT_BUDGET_TOTAL)
    for name, n, lim, over in out:
        行 += " · {0} {1:,}{2}".format(name, n, "★超" if over else "")
    return {"段": out, "总": total, "上限": CONTEXT_BUDGET_TOTAL,
            "超": 超, "超合计": 超总, "行": 行}


def context_report_check(rep: dict) -> list:
    """★ 对读数**做判据**（★ 供 `verify_all` 与界面用）：★ 返回问题列表（★ 空 = 过）。

    ★★★ 三条（★ 与方案的"超限只报红、不静默截断"同立场）：
       ① `sum(段) == 总`                  —— ★ 读数**自己要不自相矛盾**
       ② 没有段超它自己的上限
       ③ 总计不超总上限
    """
    问题 = []
    s = sum(n for _, n, _, _ in rep["段"])
    if s != rep["总"]:
        问题.append("★ 分段之和 {0} ≠ 总 {1}（★ 读数自相矛盾）".format(s, rep["总"]))
    for name, n, lim, over in rep["段"]:
        if over:
            问题.append("★ {0} = {1:,} > 上限 {2:,}".format(name, n, lim))
    if rep["超合计"]:
        问题.append("★ 合计 {0:,} > 总上限 {1:,}".format(rep["总"], rep["上限"]))
    return 问题


# ══════════════════════════════════════════════════════════════════
# ★★★ 历史字符预算（★ 记忆机制落点一的后半 · ★ 2026-10-09 本项目加）
#
#   ★★★ 它治的是哪一条（★ 实测）：
#      ★ `server.py` 的 `HISTORY_TURNS_LIMIT = 24` **只数轮、不量字符** ⇒
#      ★★ 实测：★ **第 7 轮（历史 6 轮 × ~2,246 字符）= 26,952 字符 = 约束的 94%**；
#      ★★★ **第 7 轮 + 一份 21,000 字符文档 ⇒ 约束 101,082、★ 超预算 19%。**
#      ⇒ ★ **而系统**报得出**这件事（`context_report`），★ 却**管不住**它。**
#
#   ★★★ 而管它有一条**两难**，★ 本函数的解法是唯一能同时满足两边的：
#      · ★ 不砍 ⇒ **发出去 10 万字符**（★ 贵，★ 且模型注意力被淹）；
#      · ★ 静默砍 ⇒ ★★ **违反本体系一条铁律** —— ★ `server.py:449` 逐字：
#         「**不许截断后假装读到了**」（★ 原实现是 `[:20000]` 静默截断，★ 已改成"拒"）。
#      ⇒ ★★★ **故本函数**砍，但**显形****：
#         ★ 返回 `(保留的历史, 显形说明)` —— ★ 而调用方**必须把那段说明**也发给模型**（★ 否则就是静默）。
#
#   ★★ 取舍规则（★ 明确写出来，★ 免得日后猜）：
#      ① **从最新往回取**（★ 近的比远的要紧）；
#      ② **只整轮取**（★ 不切一条消息的一半 —— ★ 半截消息比没有更坏）；
#      ③ **当前这一轮永不砍**（★ 它是用户刚说的）；
#      ④ **说明段自己也算预算**（★ 否则说明会把预算吃掉）。
# ══════════════════════════════════════════════════════════════════
#: ★ 历史段的字符上限（★ 与 `CONTEXT_BUDGET["对话历史"]` 同一个数 · ★ 一处定义）
HISTORY_CHAR_BUDGET = CONTEXT_BUDGET["对话历史"]


def bound_history(turns, *, budget: int = HISTORY_CHAR_BUDGET,
                  turns_limit: int | None = None) -> tuple:
    """★★ 把历史**限到字符预算内**，★ 并**显形说明砍了什么**。

    ★ 参数：
       · `turns`  —— ★ `[{"role":…, "content":…}, …]`（★ **已按时间正序**）
       · `budget` —— ★ 字符上限（★ 默认 `HISTORY_CHAR_BUDGET`）
       · `turns_limit` —— ★ 可选的轮数上限（★ 与字符上限**叠加** —— ★ 实测 24 轮这个数太大）
    ★★ 返回 `(保留的 turns, 说明 str)` —— ★ **说明为空串 = 一条都没砍**。
    """
    ts = [t for t in (turns or []) if isinstance(t, dict)]
    if turns_limit and turns_limit > 0:
        ts = ts[-int(turns_limit) * 2:]
    # ★ 说明段本身占位（★ 先用保守值算，★ 砍完再按真长度回填一次）
    _说明占位 = 120
    预算 = max(0, int(budget) - _说明占位)

    保留, 用 = [], 0
    for t in reversed(ts):                                                # ★ 从最新往回
        n = len(str(t.get("content", "")))
        if 用 + n > 预算 and 保留:
            break
        保留.append(t)
        用 += n
    保留.reverse()
    砍了 = len(ts) - len(保留)
    if not 砍了:
        return 保留, ""
    说明 = ("★ **本会话更早的 {0} 条消息未随本轮下发**（★ 历史字符预算 {1:,}，★ 本轮实际用 {2:,}）。"
           "★★ 故**你不知道那部分说了什么** —— ★ 不许假装记得；★ 需要时**直接问用户**。"
           "★ 原文仍在账里（★ 可查）。").format(砍了, int(budget), 用)
    return 保留, 说明


def history_note_section(note: str) -> str:
    """★ 把上面那段说明**装成「进约束的一段」**（★ 与回流段同层 · ★ 位置在回流之前）。

    ★★ 为什么单独一个函数：★ **它必须与回流一样"看得见"** ——
    ★ 否则模型会把"没下发"读成"没说过"（★ 那正是静默截断的害处）。
    """
    if not (note or "").strip():
        return ""
    return ("\n# ★★ 本轮历史不完整（★ 系统回显 · ★ 非你自报）\n"
            "★ 本会话更早的消息**没有随本轮下发** —— ★ 下面是系统给的说明：\n"
            "- {0}".format(note.strip()))

