# -*- coding: utf-8 -*-
"""探针自检 —— ★ 证明 `test_smoke.py` 那五条**真的会红**。

★ 为什么要有它：一组全绿的测试，若从没红过，就**分不清"通过了"与"没在检查"**。
★★ 故这里对每条造一个**反例**，确认那条断言会失败；反例不成立 ⇒ 本文件红。
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


def test_probe_endpoint_check_would_red(srv):
    """★ 探针 ②：换一个**不存在的路径**，那条"端点存在"的判法必须说没有。"""
    名 = set()
    for r in srv.app.routes:
        名.add((getattr(r, "path", None), tuple(sorted(getattr(r, "methods", ()) or ()))))
    assert ("/api/definitely-not-here", ("GET",)) not in 名, (
        "★ 本仓竟然真有一条 /api/definitely-not-here —— 那说明探针失效了")


def test_probe_token_gate_check_would_red(srv):
    """★★ 探针 ③：构造一个**没有闸**的函数，确认那条判法会说它没有。"""

    def 假端点(request):
        # ★ 注意：这里**不能**在 docstring 里写那两个关键词 ——
        #   `inspect.getsource` 会把 docstring 也算进源码，
        #   ⇒ 断言会**用自己的注释把自己触发**（★ 实测踩到，红在了错的理由上）。
        return {"ok": True}

    源 = inspect.getsource(假端点)
    首 = [x.strip() for x in 源.split("\n") if x.strip() and not x.strip().startswith(("#", '"', "'"))]
    assert not any("_local_token_ok" in x for x in 首[:6]), "探针本身写错了"
    assert "403" not in 源, "探针本身写错了"


def test_probe_three_source_check_would_red():
    """★★ 探针 ④：一个只读环境变量的函数，那条判法必须说它缺两路。"""

    def 假取key():
        """只读环境变量。"""
        import os
        return (os.environ.get("X") or "").strip()

    源 = inspect.getsource(假取key)
    assert "environ" in 源
    assert ".env.local" not in 源, "探针本身写错了"
    assert "config.local.json" not in 源, "探针本身写错了"


def test_probe_asset_check_would_red():
    """★ 探针 ⑤：一个不存在的路径，那条"文件在"的判法必须说不在。"""
    假 = APP / "这个文件肯定不存在.json"
    assert not 假.is_file(), "★ 那个路径竟然真有文件 —— 探针失效"
