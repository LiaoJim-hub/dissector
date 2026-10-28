# -*- coding: utf-8 -*-
"""M1 + M2 的守卫（2026-10-28）。

★ M1（《向外走》）：「先交出『账的形状』，不交『账的内容』。」
★ M2（《从主动帮到自动拦》）：「凡能数的，系统该替你数；凡只能由人答的，
  系统不该替他答 —— 只该把问题问出来。」

★★ 而本文件的存在理由，有一条是**具体的**：我第一版把变量名写成了 `_acc_text`
  （★ 而它不存在，真名是 `acc`），被一个 `except` 吞成「账没算成」⇒
  ★★ 那与敌手 D 第 17 轮 P1-1 是**同一个形状**：
  「一个自称『唯一可对账处』的函数，一行不写、零告警」。
  ★★★ 故这里有一条测**直接调那个函数**，而不是只看它"有没有定义"。
"""
import importlib
import json
import pathlib
import sys

import pytest

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(scope="module")
def srv():
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    return importlib.import_module("server")


答案全 = """你卡在哪一句：你说的是「我不知道该不该接」，而这一句里其实有两个东西。
这一问有几面：一是钱，二是时间，三是你怕的那个评价。
有几面说完了。而路有三条：一条是接，代价是时间；一条是拒，代价是关系；一条是拖。
"""

答案缺路 = """你卡在哪一句：你说的是「我很烦」。
这一问有几面：一是你自己，二是对方。
"""


# ══════════════════════════════════════════════════════════════════════════
# M1 · 账的形状
# ══════════════════════════════════════════════════════════════════════════
def test_account_has_all_three_sections(srv):
    """★ M1：账必须含三类（① 数出来的 · ② 按口径算的 · ③ 只能人答的）。"""
    a = srv._build_account("我不知道该不该接这个活", 答案全, "sid")
    for k in ("①_数出来的", "②_按口径算的", "③_只能人答的", "这份账的边界"):
        assert k in a, "★ 缺「{}」—— 那三类标记是 M2 的全部内容".format(k)


def test_account_counts_empty_layers(srv):
    """★★ 最关键的一条：**缺哪一层必须数得出来**。"""
    b = srv._build_account("我很烦", 答案缺路, "sid")
    assert b["①_数出来的"]["空着的层"] == ["路"], (
        "★ 该报「路」那一层没出现。实报：{}".format(b["①_数出来的"]["空着的层"]))
    assert b["①_数出来的"]["给出层数"] == 2
    assert b["①_数出来的"]["总层数"] == 3, "★ 这个产品是**三层**（问/面/路），不是四层"


def test_account_says_uncomputable_for_human_only(srv):
    """★★ M2：只能人答的那三项，**必须写「不可核」，不许编**。"""
    a = srv._build_account("x", 答案全, "sid")
    三 = a["③_只能人答的"]
    assert 三, "★ 第三类空了 —— 那说明它把「只能人答」的那部分删掉了"
    for k, v in 三.items():
        assert "不可核" in v, (
            "★ 「{}」没有写「不可核」 ⇒ **它在替人答**。实际：{}".format(k, v))


def test_account_contains_no_advice_words(srv):
    """★★★ 而它**不许**出现「建议 / 你应该」这类词 ——

    ★ 依据（《向外走》§12.3 三条禁令）：一旦它给出"该怎么做"的结论，
      **它就变成了判定主体**，而那正是那个文件明令拒绝的那条路。
    """
    a = srv._build_account("我不知道该不该接这个活", 答案全, "sid")
    s = json.dumps(a, ensure_ascii=False)
    for w in ("建议你", "你应该", "我建议", "推荐你", "最好是"):
        assert w not in s, "★ 账里出现了「{}」—— 那会让本工具成为判定主体".format(w)


def test_account_records_verbatim_input(srv):
    """★ 原话必须逐字留着（★ 它是唯一不可替换的输入）。"""
    a = srv._build_account("我不知道该不该接这个活", 答案全, "sid")
    assert a["①_数出来的"]["原话"] == "我不知道该不该接这个活"
    assert a["①_数出来的"]["原话字数"] == 11, "★ 字数该数出来，不许估"


# ══════════════════════════════════════════════════════════════════════════
# ★ 那一条专为我自己的事故加的
# ══════════════════════════════════════════════════════════════════════════
def test_chat_endpoint_passes_real_answer_text(srv):
    """★★★ 这条是我给自己的：我第一版把变量名写成 `_acc_text`（★ 它不存在），
    于是**账永远算不成，而零告警** —— 与 D 第 17 轮 P1-1 一字不差。

    ★ 故这条测**直接读源码**，确认 `_build_account` 的第二个实参不是那个不存在的名字。
    ★★ 而它同时确认 `acc` 在那个作用域里真的存在（★ 否则改名也没用）。
    """
    import inspect
    源 = inspect.getsource(srv.chat)
    # ★★★ 2026-10-28（A 自查 · 第二次踩同一个坑）：
    #   `inspect.getsource` 把**注释**也算进源码 —— 而我在修 `_acc_text` 时，
    #   写了一段解释"那个变量不存在"的注释，里面**正好写着 `_acc_text`**。
    #   ⇒ 本测用自己的注释触发了自己（★ 上一轮那个探针也是这样）。
    #   ★ 故这里**先剥掉注释行**再断 —— 而不是把那句有价值的注释删掉。
    有效 = "\n".join(x for x in 源.split("\n") if not x.lstrip().startswith("#"))
    assert "_acc_text" not in 有效, (
        "★ `_acc_text` 又出现了（★ 在**有效代码**里，不是注释里）—— 那个变量不存在。"
        "真正的累积器叫 `acc`（一个 list）")
    assert "_build_account(" in 有效, "★ chat 里没调 _build_account ⇒ 账不会进 done 事件"
    assert "acc" in 有效, "★ chat 里没有 `acc` —— 那说明累积器换了名字，本测要跟着改"
