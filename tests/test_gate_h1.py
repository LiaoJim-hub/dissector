# -*- coding: utf-8 -*-
"""H1 的守卫 —— 「分两道发」那道闸（2026-10-28）。

★ 依据：思考台第 ④ 条（逐字）：
  「模型吐 token → 服务端逐片累积，不往外发 →
   命中『路』的标记词，或累积到 N 字仍无『路』⇒ 打开闸，把已累积的全部一次性发出 →
   之后正常流式。」

★★ 而它同时划清了这道闸的**精度边界**（逐字）：
  「判『这一层写完了没有』判不了（语义）；判『这一层有没有出现过』判得了。」
  「标记词会假阳……那不是 bug，是这道闸的已知精度。」

★★★ 故本文件守三件：
  ① 那道判据**真的判得出来**（不是恒假也不是恒真）
  ② 缺路时**必须如实说一句**（★ 那是记账，不是判断）
  ③ 那道闸**真的在流式路径里**（★ 否则它只是一段死代码）
"""
import importlib
import inspect
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
# ① 判据真的判得出来
# ══════════════════════════════════════════════════════════════════════════
def test_hit_road_detects_real_text(srv):
    """★ 有「路」的文本 ⇒ 判 True。"""
    assert srv._hit_road("有几面说完了。而路有三条：一条是接，代价是时间。") is True
    assert srv._hit_road("这条路可以停") is True


def test_hit_road_rejects_text_without_road(srv):
    """★★ 只说「问」和「面」的文本 ⇒ 判 False（★ 否则这道闸恒真，等于没装）。"""
    assert srv._hit_road("你卡在哪一句：你说的是「我不知道该不该接」。") is False
    assert srv._hit_road("这一问有几面：一是钱，二是时间。") is False


def test_probe_hit_road_would_red(srv):
    """★ 探针：一个**恒真**的判据必须被上面那两条区分出来。"""
    def 恒真(x):
        return True
    assert srv._hit_road("只有问和面，没有路") is False, "本判据恒真了！"
    assert 恒真("只有问和面，没有路") is True, "探针本身写错了"


# ══════════════════════════════════════════════════════════════════════════
# ② 缺路时必须如实说一句（★ 记账，不是判断）
# ══════════════════════════════════════════════════════════════════════════
def test_missing_note_names_the_missing_layer(srv):
    """★★ 那句必须**指名道姓**说「没拆到『路』」—— ★ 不许含糊成「信息不全」。"""
    n = srv._gate_missing_note()
    assert "路" in n, "★ 那句没说哪一层缺了 —— 那是含糊"
    assert "没拆到" in n, "★ 那句没说「没拆到」—— 用户会以为它还在写"


def test_missing_note_offers_two_ways(srv):
    """★★★ 而它必须给**两条路**（★ 那是 L1 的兜底精神：不许变成"你得先想清楚才能用"）。"""
    n = srv._gate_missing_note()
    assert "(a)" in n and "(b)" in n, "★ 它只给了一条路 —— 那会让用户觉得被卡住"


def test_missing_note_has_no_advice(srv):
    """★ 而它不许出现「建议 / 你应该」—— 那是判断，不是记账。"""
    n = srv._gate_missing_note()
    for w in ("建议你", "你应该", "我建议", "最好是"):
        assert w not in n, "★ 补的那句出现了「{}」—— 那是判断".format(w)


# ══════════════════════════════════════════════════════════════════════════
# ③ 那道闸真的在流式路径里
# ══════════════════════════════════════════════════════════════════════════
def test_gate_is_in_the_streaming_path(srv):
    """★★★ 这条防的是「一段死代码」：闸必须真的在 `chat` 的流式生成器里。

    ★ 怎么判：读 `chat` 源码（剥掉注释）⇒ 必须出现三样：
      `_gate_open`（状态）· `_hit_road`（开闸判据）· `_GATE_MAX_CHARS`（"放弃"阈值）
    ★★ 而它还必须**在流结束处兜底**（否则无「路」且短的回答会一片空白）。
    """
    import inspect as _i
    源 = _i.getsource(srv.chat)
    有效 = "\n".join(x for x in 源.split("\n") if not x.lstrip().startswith("#"))
    for 标 in ("_gate_open", "_hit_road", "_GATE_MAX_CHARS"):
        assert 标 in 有效, "★ 闸缺「{}」—— 它没真的装进流式路径".format(标)
    assert "_gate_missing_note()" in 有效, "★ 闸开了却没补那句「没拆到路」"


def test_gate_threshold_is_a_number(srv):
    """★ 阈值是个可调的数（★ 它不承诺精度，只决定"等多久"）。"""
    assert isinstance(srv._GATE_MAX_CHARS, int)
    assert 300 <= srv._GATE_MAX_CHARS <= 3000, (
        "★ 阈值 {} 不在合理区间：太小 ⇒ 几乎每轮都放弃；太大 ⇒ 白屏".format(
            srv._GATE_MAX_CHARS))
