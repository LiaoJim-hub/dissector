# -*- coding: utf-8 -*-
"""H2 + L1 的守卫（2026-10-28）。

★ H2 依据（《从主动帮到自动拦》建议三，逐字）：
  「一个跨轮的量，且这个量由服务端算、不由我说。」
  「它把『自我报告』变成『外部读数』。」
★ L1 依据（同报告建议一，逐字）：
  「拦不需要知道『该做什么』，只需要知道『什么不行』。」
  ★★ 而它也警告：「它会误伤 —— ……触发条件必须窄……否则它天天卡人，卡几次就被人绕过。」
"""
import importlib
import pathlib
import sys

import pytest

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(scope="module")
def srv():
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    return importlib.import_module("server")


# ══════════════════════════════════════════════════════════════════════════
# H2 · 「给了几层」由服务端数
# ══════════════════════════════════════════════════════════════════════════
def test_count_layers_counts_three(srv):
    """★ 三层都有 ⇒ 每层都非零。"""
    n = srv._count_layers("你卡在哪一句：X。这一问有几面：A。路有三条：B。")
    assert n["问"] > 0 and n["面"] > 0 and n["路"] > 0, "★ 三层没数全：{}".format(n)


def test_count_layers_reports_zero_for_missing(srv):
    """★★ 缺一层 ⇒ 那一层必须是 **0**（★ 不许因为"差不多"就非零）。"""
    n = srv._count_layers("你卡在哪一句：X。这一问有几面：A。")
    assert n["路"] == 0, "★ 「路」没出现却数成 {} —— 那会把缺层藏掉".format(n["路"])


def test_road_marks_are_one_source(srv):
    """★★★ 这条防的是「两处真值必漂」——

    ★ 实测撞到过：`_GATE_ROAD_WORDS` 加了「路有」而 `_LAYER_MARKS` 里那份没加
      ⇒ 同一段文本，`_hit_road` 判 True 而 `_count_layers` 数 0（**冤枉一整轮**）。
    ★★ 故这里直接断言：`_LAYER_MARKS` 里「路」那个元组**就是** `_GATE_ROAD_WORDS` 本身。
    """
    路词 = dict(srv._LAYER_MARKS)["路"]
    assert 路词 is srv._GATE_ROAD_WORDS or tuple(路词) == tuple(srv._GATE_ROAD_WORDS), (
        "★ 「路」的标记词有**两处**：_LAYER_MARKS 与 _GATE_ROAD_WORDS 各自一份。"
        "★ 两处必漂 —— 而实测它已经漂过一次。")


def test_hit_road_and_count_layers_agree(srv):
    """★★★ 两处判据对同一段文本必须给出**一致的**结论。

    ★ 这是那条"两处必漂"的**运行时**守卫（上面那条守的是定义，这条守的是行为）。
    """
    for 文 in ("路有三条：一条接，一条拒。",
               "有一条路是拒绝。",
               "你卡在哪一句：X。这一问有几面：A。"):
        有 = srv._hit_road(文)
        数 = srv._count_layers(文)["路"] > 0
        assert 有 == 数, (
            "★ 同一段文本，`_hit_road` 说 {} 而 `_count_layers` 说 {} —— 两处漂了。"
            "文：{}".format(有, 数, 文[:40]))


def test_layers_echo_names_missing_layer(srv):
    """★★ 回显必须**指名**缺哪一层，且说明那个数是服务端算的。"""
    e = srv._layers_echo("你卡在哪一句：X。这一问有几面：A。")
    assert "路" in e, "★ 回显里没提缺的那一层"
    assert "服务端" in e, "★ 没说清那个数由服务端算 —— 那它就又成了自我报告"
    assert "2/3" in e or "2 / 3" in e, "★ 没报出 2/3。实际：{}".format(e[:160])


def test_layers_echo_empty_on_no_history(srv):
    """★ 没有上一轮 ⇒ 回空串（★ 不编一个"0/3"）。"""
    assert srv._layers_echo("") == ""


# ══════════════════════════════════════════════════════════════════════════
# L1 · 输入太模糊 ⇒ 问回一句（★ 而必须带兜底）
# ══════════════════════════════════════════════════════════════════════════
def test_vague_blocks_emotion_only(srv):
    """★ 只有情绪 ⇒ 拦。"""
    for x in ("我很烦", "不知道", "迷茫"):
        v, why = srv._is_too_vague(x)
        assert v, "★ 「{}」该被判太模糊（它是纯情绪）".format(x)
        assert why, "★ 拦了却不说为什么 —— 那用户只能自己猜"


def test_vague_blocks_abstract_only(srv):
    """★ 全是抽象词而无具体场景 ⇒ 拦。"""
    v, why = srv._is_too_vague("人生的意义是什么")
    assert v, "★ 该拦"
    assert "抽象" in why, "★ 该说清是「抽象」，不是「太短」。实际：{}".format(why)


def test_vague_passes_specific_text(srv):
    """★★★ 这一条最重要：**带具体场景的一律放行** ——

    ★ 因为这道闸的已知风险是**误伤**，而误伤的代价比"少拦一次"高得多。
    """
    for x in ("老板今天跟我说合同要提前签，我拿不准要不要签",
              "我不知道该不该接这个活，因为下周就到期了",
              "他被客户骂了，想辞职",
              "这个方案客户说要砍一半预算"):
        v, _ = srv._is_too_vague(x)
        assert not v, "★ 「{}」被误伤了 —— 它有具体场景".format(x[:30])


def test_vague_passes_empty(srv):
    """★ 空输入不在这里管（交给上游既有逻辑，★ 不重复管）。"""
    v, _ = srv._is_too_vague("")
    assert not v


def test_vague_reply_has_both_options(srv):
    """★★★ L1 的**命门**：那句问回话必须有 (a) 和 (b)，而 (b) 是兜底。

    ★ 没有 (b) ⇒ 它就变成「你要先想清楚才能用」——
      ★★ **而那与整个产品的立场相反**（见 `_vague_reply` 的注释）。
    """
    r = srv._vague_reply("我很烦", "这句里只有情绪")
    assert "(a)" in r, "★ 没有 (a) 补一句具体场景那条路"
    assert "(b)" in r, (
        "★ 没有 (b) 兜底 —— 那 L1 就变成了「你得先想清楚才能用」，"
        "而那与这个产品的立场相反")
    assert "就这样" in r, "★ (b) 那条没写清是「就这样」"

    # ★ 而它不许变成"你不够清楚"那种话。
    # ★★★ 2026-10-28（A 自查 · 我的断言太粗）：第一版直接查「你没说清」四个字，
    #   而那句文案是「**不是**你没说清」—— 它**恰恰在替用户开脱**。
    #   ⇒ 故这里只查**不带否定词**的指责形态。
    for w in ("你说得太模糊", "请你说清楚一点", "你先想清楚"):
        assert w not in r, "★ 那句问回话在指责用户：{}".format(w)
    # ★ 而"没说清"这四个字只许出现在**否定**里（「不是你没说清」）
    if "没说清" in r:
        assert "不是你没说清" in r, (
            "★ 「没说清」出现了，而不在「不是你没说清」这个否定里 —— 那是在指责用户")


def test_vague_reply_says_it_might_be_my_fault(srv):
    """★★ 而它必须先说「可能是我没听懂」—— ★ 不许把这个判据的失败算在用户头上。"""
    r = srv._vague_reply("我很烦", "只有情绪")
    assert "我没听懂" in r, (
        "★ 那句话必须先承担一半责任（「可能是我没听懂」）—— "
        "因为这道闸本身就会误伤，而用户不知道它有多准。")
