# -*- coding: utf-8 -*-
"""L1 收紧的守卫（2026-10-28 · 依你截图里那 6 句的实测）。

★ 问题：「明天上海天气怎么样」原来**放过**了 —— 而它不是这个工具该做的事。
★★ 原因：「明天」在"具体"词表里 ⇒ 它被当成"有时间可指"。
★★★ 改法：把「明天」摘出去（★ 而"场景"仍由 老板/客户/合同/这单/30 万 那些词建）。
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
# ★ 该拦的（★ 它们不是"拆解材料"）
# ══════════════════════════════════════════════════════════════════════════
def test_blocks_weather_question(srv):
    """★★ 「明天上海天气怎么样」该被拦 —— ★ 那是**查天气**，不是"卡住了"。"""
    v, why = srv._is_too_vague("明天上海天气怎么样？")
    assert v, (
        "★ 它被放过了 —— 而「明天」被当成了「有时间可指」。"
        "★ 而那不是「你卡在哪」那个时间，只是话题里的日期。")
    assert why, "★ 拦了却不说为什么"


def test_blocks_typo_request(srv):
    """★ 「帮我改个错字」该被拦 —— ★ 那是一件**可执行的小任务**，不是拆解。"""
    v, _ = srv._is_too_vague("帮我改个错字：的地得")
    assert v


# ══════════════════════════════════════════════════════════════════════════
# ★★ 不该拦的（★ 这五条是你截图里真该拆的）
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("x", [
    "我这套东西能卖多少钱",
    "客户要我把出处省掉，我该答应吗",
    "这单 30 万，我该接吗",
    "我团队里有人老是拖，怎么办",
    "我不知道该不该接这个活，因为下周就到期了",
])
def test_passes_real_questions(srv, x):
    """★★★ 这五条**一条都不许拦** —— ★ 而它们正是你截图里那类。"""
    v, why = srv._is_too_vague(x)
    assert not v, "★ 「{}」被误伤了（原因：{}）".format(x, why)


def test_passes_scene_with_today(srv):
    """★★ 而「今天」要**留着** —— ★ 「老板今天跟我说」那种才是场景。

    ★★★ 这条守的是"别改过头"：摘「明天」而**不摘「今天」/「昨天」**。
    """
    v, _ = srv._is_too_vague("老板今天跟我说合同要提前签，我拿不准要不要签")
    assert not v, "★ 「今天」也被摘掉了 —— 那会误伤真正的场景句"


def test_probe_would_red(srv):
    """★ 探针：一个恒真的判据必须被上面几条区分出来。"""
    def 恒真(x):
        return True
    assert srv._is_too_vague("这单 30 万，我该接吗")[0] is False, "判据恒真了！"
    assert 恒真("这单 30 万，我该接吗") is True, "探针本身写错了"
