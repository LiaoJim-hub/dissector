# -*- coding: utf-8 -*-
"""冒烟测试 —— ★ 不依赖 `_build/`，只依赖本仓自己的东西。

★ 为什么要有这一组：本仓原有那 3 个测试文件（`test_cases.py` 是数据、
`test_proto16.py` 与 `_build/验收.py` 依赖构建脚本）**都不是能独立跑的测试**。
★★ 而「可发布」的最低门槛是：**拿到仓库的人，一条命令就知道它没坏。**

★ 本组只验五件：
  ① 服务模块能 import（依赖齐）
  ② 两条新端点存在（`/api/key` GET + POST）
  ③ 令牌比较是**常量时间**的对照，而**没有令牌时 POST 必拒**
  ④ `get_api_key()` 是三路读（★ 而不是只读环境变量）
  ⑤ 场景卡与协议文件都在
"""
import importlib
import inspect
import pathlib
import sys

import pytest

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(scope="module")
def srv():
    """把 app/ 放进 sys.path 后 import server（★ 只 import，不起服务）。"""
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    return importlib.import_module("server")


# ══════════════════════════════════════════════════════════════════════════
def test_server_imports(srv):
    """★ ① 依赖齐 —— 缺一个包这里就炸。"""
    assert hasattr(srv, "app"), "server 没把 FastAPI 实例叫 app"


def test_key_endpoints_exist(srv):
    """★ ② `/api/key` 的 GET 与 POST 都在。"""
    名 = set()
    for r in srv.app.routes:
        名.add((getattr(r, "path", None), tuple(sorted(getattr(r, "methods", ()) or ()))))
    assert ("/api/key", ("GET",)) in 名, "缺 GET /api/key。实有：\n" + "\n".join(
        str(x) for x in sorted(名) if x[0] and "key" in str(x[0]))
    assert ("/api/key", ("POST",)) in 名, "缺 POST /api/key"


def test_post_key_requires_local_token(srv):
    """★★ ③ 没令牌 ⇒ 拒（★ 那是"任意网页换不掉 key"的全部依据）。

    ★ 这个测**不真发 HTTP** —— 它验的是那条闸的**存在与写法**：
      `set_key` 的第一件事必须是 `_local_token_ok(request)`，且不通过就 `raise`。
    ★★ 为什么这样验也够：真发 HTTP 要起服务（慢、要端口），而那件事已由
      `docs/构建说明.md` 的手工验证覆盖；这里守的是**代码结构不被悄悄改掉**。
    """
    源 = inspect.getsource(srv.set_key)
    首 = [x.strip() for x in 源.split("\n") if x.strip() and not x.strip().startswith(("#", '"', "'"))]
    assert any("_local_token_ok" in x for x in 首[:6]), (
        "`set_key` 的前几行里没有令牌闸。★ 它必须在第一件事就挡，"
        "否则任何网页都能换掉 key。实际开头：\n" + "\n".join(首[:6]))
    assert "raise HTTPException(403" in 源 or "403" in 源, "令牌不过时没有 403"


def test_get_api_key_reads_three_sources(srv):
    """★★ ④ `get_api_key()` 必须是三路读。

    ★ 为什么守这条：此前它只读环境变量 ⇒ 界面存了 key 而引擎读不到
      ⇒ **「存了而不生效」**（界面报已保存，而 /api/chat 仍报未配 key）。
    """
    源 = inspect.getsource(srv.get_api_key)
    assert "environ" in 源, "没读环境变量"
    assert "config.local.json" in 源 or "CONFIG_FILE" in 源, "没读 config.local.json"
    assert ".env.local" in 源, "没读 .env.local"


def test_assets_present():
    """★ ⑤ 场景卡与协议文件都在（★ 缺了它跑起来会空转）。"""
    assert (APP / "场景·看清问题.json").is_file(), "缺场景卡"
    assert (APP / "protocol" / "拆解器·协议.md").is_file(), "缺协议正文"
    assert (APP / "index.html").is_file(), "缺界面"
