# -*- coding: utf-8 -*-
"""敌手 D 第 17 轮那五条伤的守卫（2026-10-28 加）。

★ 它的原话：「本轮四条 P0/P1 伤，测试零覆盖…… 特别是
  `test_get_api_key_reads_three_sources` 把**违反文首铁律的实现**钉成了通过项：
  ★★ **测试不是中立的白名单，它这次站在了 bug 一边。**」

★★ 故本文件守的**不是"结构存在"，是"声称与行为一致"**。
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
# P0-1 · base_url 白名单不能只锁 HTTP 一条路
# ══════════════════════════════════════════════════════════════════════════
def test_base_url_whitelist_is_one_function(srv):
    """★★ P0-1：白名单必须是**一个函数**，而 `set_config` 与 `load_config` 都调它。

    ★ 为什么守"一个函数"而不是"两处都有"：D 的原话是
      「加与 `set_config` 同一白名单（**同一函数、不是两处**）」——
      ★★ 两处各写一份，就是**两个会漂的落点**。
    """
    assert hasattr(srv, "_base_allowed"), (
        "没有 `_base_allowed()` —— 那说明白名单还是散在 `set_config` 里")
    源 = inspect.getsource(srv.load_config)
    assert "_base_allowed" in 源, (
        "★ `load_config()` 没调白名单 ⇒ 手改 config.local.json 就能把 key 送去任意主机。"
        "★ 那正是 P0-1。")


def test_base_allowed_rejects_foreign_host(srv):
    """★★ 白名单真的会拒（★ 不是个恒真的摆设）。"""
    assert srv._base_allowed("https://api.deepseek.com") is True
    assert srv._base_allowed("https://api.deepseek.com/") is True     # ★ 尾斜杠
    assert srv._base_allowed("http://127.0.0.1:8480") is False         # ★ D 的假上游
    assert srv._base_allowed("https://evil.example.com") is False
    assert srv._base_allowed("") is False


def test_probe_base_allowed_would_red(srv):
    """★ 探针：一个恒真的判据必须被这条测区分出来。"""
    def 恒真(u):
        return True
    assert srv._base_allowed("http://127.0.0.1:8480") is False, "白名单没拒！"
    assert 恒真("http://127.0.0.1:8480") is True, "探针本身写错了"


# ══════════════════════════════════════════════════════════════════════════
# P0-3 · 同一个 api_key 字段：不能一边读它、一边报它"已忽略请删除"
# ══════════════════════════════════════════════════════════════════════════
def test_api_key_field_is_not_tainted(srv):
    """★★★ P0-3：`api_key` 是界面存 key 的正路 ⇒ **它不许被判成"残留"**。

    ★ 病灶：`KEY_LIKE` 里有 `"api_key"` ⇒ `load_config()` 判它 tainted ⇒
      `/api/health` 说「该字段已被忽略，**请删除该字段**」。
      ★★ 而 `get_api_key()` **就在读它** ⇒ 用户照 hint 删 ⇒ **key 丢了**。
    ★★★ 而那句话本身是**假话**（"已被忽略"）—— 本体系最忌的就是这个。
    """
    assert "api_key" not in srv.KEY_LIKE, (
        "★ `KEY_LIKE` 里还有 `api_key` ⇒ 界面存的 key 会被报成「残留、请删除」，"
        "而它其实**在被使用**。★ 那是 P0-3。实际值：{}".format(srv.KEY_LIKE))


def test_sk_prefix_still_flagged(srv):
    """★ 而**真正的脏**仍要判：`sk-` 出现在 `api_key` 之外的字段里 ⇒ 该报。"""
    assert "sk-" in srv.KEY_LIKE, "★ 那条真防线被删掉了（`sk-` 该留）"


# ══════════════════════════════════════════════════════════════════════════
# P1-1 · 出网账必须真的能写
# ══════════════════════════════════════════════════════════════════════════
def test_egress_file_is_defined(srv):
    """★★ P1-1：`EGRESS_FILE` 必须**有定义**。

    ★ 病灶：`_egress_log` 用了它而全仓零定义 ⇒ 每次 `NameError`，
      被它自己的 `except Exception: pass` 吞掉 ⇒
      ★★ 一个自称"唯一可对账处"的函数，**一行不写、零告警**。
    """
    assert hasattr(srv, "EGRESS_FILE"), (
        "★ `EGRESS_FILE` 未定义 ⇒ 出网账永远不会落笔（P1-1）")
    assert str(srv.EGRESS_FILE).endswith("egress.jsonl")


def test_egress_log_actually_writes(srv, tmp_path, monkeypatch):
    """★★★ 而它必须**真能写下一行** —— ★ 不是"有定义"就算完。"""
    目标 = tmp_path / "egress.jsonl"
    monkeypatch.setattr(srv, "EGRESS_FILE", 目标)
    srv._egress_log("https://api.deepseek.com/chat/completions", "test", 123)
    assert 目标.is_file(), "★ 调了 `_egress_log` 而文件没生成 —— 它还在静默吞异常"
    行 = 目标.read_text(encoding="utf-8").strip().split("\n")
    assert len(行) == 1 and "api.deepseek.com" in 行[0]


# ══════════════════════════════════════════════════════════════════════════
# P1-2 · mode 那个"可以任意书写、与行为无关"的账面字段
# ══════════════════════════════════════════════════════════════════════════
def test_chat_in_has_no_drifting_mode_field(srv):
    """★★ P1-2：`ChatIn` 里**不许有 `mode`**。

    ★ 病灶：三处注释说"mode 只许 light（写死）"，而实现是 `mode: str = "light"`
      **无任何校验** ⇒ 传 `protector` 也照记进两本账。
    ★★ D 的建议：「`mode` 字段干脆删掉，只留 `protector` —— **少一个会漂的字段**」。
    """
    字段 = getattr(srv.ChatIn, "model_fields", None) or getattr(srv.ChatIn, "__fields__", {})
    assert "mode" not in 字段, (
        "★ `ChatIn.mode` 又在 ⇒ 那个字段可以任意书写、而行为由 `protector` 决定 ⇒ 账面会漂")


def test_tier_mode_is_single_source(srv):
    """★ 而档位真值仍在**一处**。"""
    assert srv.TIER_MODE == "light"


# ══════════════════════════════════════════════════════════════════════════
# ★ 我自己那个事故的守卫：body.model 不许被改成别的东西
# ══════════════════════════════════════════════════════════════════════════
def test_set_config_reads_body_model(srv):
    """★★★ 这条是我给自己的：2026-10-28 我用字符串替换删 `body.mode` 时，
    **把 `body.model` 误改成了 `TIER_MODEl`** —— 而语法过了、9 条测全绿。

    ★ 全绿的原因是：那 9 条测**没有一条碰 `set_config` 的 model 分支**。
    ★★ 故这条测存在的意义不是"守 set_config"，是**守"全绿不等于改对了"**。
    """
    源 = inspect.getsource(srv.set_config)
    assert "body.model" in 源, (
        "★ `set_config` 里没有 `body.model` —— 模型名那个分支可能被误改了")
    assert "TIER_MODEl" not in 源, "★ 那个误改又回来了（`TIER_MODEl`）"
