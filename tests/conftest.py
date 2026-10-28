# -*- coding: utf-8 -*-
"""pytest 入口：把 app/ 加进 sys.path，让测试能 import 到它。"""
import pathlib
import sys

_APP = pathlib.Path(__file__).resolve().parents[1] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))
