# -*- coding: utf-8 -*-
r"""
拆解器（外发 · 最精简版）· 本地服务

★★★ 本文件是**裁剪产物**（★ 不是重写）：★ 从一个更完整的内部版本
   按白名单裁剪而成 —— ★ 保留的都是**核心四件 + 壳**，★ 去掉的都是**业务侧**（见文末清单）。
   ★ 出处**不写在这里**：★ 这类"来源路径/项目名"属**本地信息**，★ 外发包里一律不留。

★★ 这个工具只做一件事：**帮人把问题本身看清 —— 不替他下结论。**
   · **两个档位**：工作模式（默认）· 护根（★ 由界面那个勾选框**显式开** —— ★ 它是一个动作，不是一个默认值）。
   · **只有一种输出**：自然流动的正文 + 一行凭据（★ 凭据三样，含相位指纹）。
   · **不带框架**：进提示词的协议正文 = 一份 ≤3 KB 的「看清问题」层位表，★ 不是那份 91 KB 协议。

★ 与原版的差别（裁剪清单 · 逐块）：
   去掉了：联网检索 · 读/写本地文件工具 · 文档上传库 · 图片 OCR · 能力边界账端点 ·
           方向史端点 · 行使史只读端点 · 协议漂移闸 · 三账一览（前端）· 档位/护根开关。
   保留了：会话（新建/列/读/改名/删/导出）· 对话（SSE 流式）· 配置（只读非敏感项）·
           连通性自检 · 健康检查 · **回流**（核心四件第④）· **判据读数落账**。

★ 两条铁律：
   ① **Key 的取法**（★ 2026-10-28 更新 · 依敌手 D 第 17 轮 P0-3）：三路，**环境变量优先** ——
      `DEEPSEEK_API_KEY` ⇒ `config.local.json` 的 `api_key` ⇒ `.env.local`。
      ★★ 而 HTTP 写入**只走 `POST /api/key`，且必须带本机令牌**（`x-rootthink-token`）——
      故「任意网页换不掉它」这条**仍然成立**（★ 它不是"不经 HTTP"，是"经 HTTP 但要令牌"）。
      ★ 文首此前写的「不经 HTTP、不落 config.local.json」**已与实现相反**，故改掉。
   ② **缺 key ⇒ 拒服务并给出设置指引** —— ★ 不许静默降级成"看起来能用"。
   ★★ 第三条（本外发版加）：**档位可对账** —— `mode` 只许 `light`（★ 写死）；`protector` **只由使用者显式开**
      （★ 默认 `False`）⇒ ★ 真值只有一处，★ 且**每轮落账**（★"防漂"要的是"真值唯一且可对账"，★ 不是"值恒定"）。

★ 隐私修（依「通过项」规则 —— ★ 密钥必须由**本件之外**的东西产出）：
  ① **API Key 三路读，而 HTTP 写入必须带本机令牌**（2026-10-28 改 · 依敌手 D 第 17 轮 P0-3）。
     · 原来的理由仍然成立：**允许它由无闸的 HTTP 填 ⇒ 任意网页都能把它换掉**。
     · ★★ 而现在的做法不是"禁 HTTP"，是**给 HTTP 那条路加令牌闸** ——
       `POST /api/key` 要 `x-rootthink-token`（启动时随机生成、只注入本服务打开的页面）。
     · ★ 文件里出现 `sk-`（在 `api_key` 之外的字段里）仍判脏 —— 那条防线保留。
  ② **`GET /api/config` 不再回 key 的任何片段**（此前回 `key_hint`＝后 4 位 + 是否已设）。
  ③ **`POST /api/config` 拒收 `api_key` 字段**（400，并说明改法）。
  ④ **缺 key 时本进程仍可起，但 `/api/chat`、`/api/test` 拒服务并给出设置指引** ——
     ★ 这是**有意的失败模式**：不许静默降级成"看起来能用"。
"""
import asyncio
import hashlib
import json
import pathlib
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel

# ★★ 本外发版：把**程序目录**放进 `sys.path`（★ 必须在下面 import 同目录模块**之前**做）
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# [atomic-io-import:BEGIN]
# ★ B-35/B-37：原子追加与原子替换（持锁，防丢行/防半截文件）
try:
    import atomic_io
except Exception as _e:                                   # noqa: BLE001
    # ★ **不静默降级**：明说回退到了无锁写入，并给出原因
    atomic_io = None                                      # type: ignore[assignment]
    import sys as _sys
    print("[atomic_io] ★ 不可用（{0}: {1}）⇒ 回退到**无锁**写入，并发下可能丢行".format(
        type(_e).__name__, _e), file=sys.stderr)
# [atomic-io-import:END]

# [atomic-io-fallback:BEGIN]
if atomic_io is None:                                     # ★ 回退（已在上方明确告警）
    def _append_line_fallback(_p, _o):
        with open(_p, "a", encoding="utf-8", newline="\n") as _f:
            _f.write(json.dumps(_o, ensure_ascii=False) + "\n")
    class _AI:                                            # 极简替身，只补被用到的两个函数
        append_line = staticmethod(_append_line_fallback)
        @staticmethod
        def write_json_atomic(_p, _o, indent=1):
            pathlib.Path(_p).write_text(json.dumps(_o, ensure_ascii=False, indent=indent),
                                        encoding="utf-8")
    atomic_io = _AI()                                     # type: ignore[assignment]
# [atomic-io-fallback:END]



APP_DIR = Path(__file__).resolve().parent
# ★★★ 硬纪律（★ 本外发版加）：`data\` 与 `history\` 在 **app\ 外面**（与 app 同级）。
#   ★ 为什么：本包承诺**整包替换式升级** ⇒ ★ 若数据住在 app\ 里，★ 升级会**覆盖使用者的账**。
#   ★（对作者是私有数据，★ 对使用者是他自己的私有数据 —— 两处同一条纪律。）
DATA_DIR = APP_DIR.parent / "data"
SESSIONS_FILE = DATA_DIR / "sessions.json"
# ★★ 同上：`config.local.json` 是**使用者的设置**（模型名 / max_tokens / base_url）⇒ ★ 也住 app 外面。
CONFIG_FILE = APP_DIR.parent / "config.local.json"
# ★ 本外发版**不带那份 91 KB 协议**（★ 见 build_system_prompt：协议正文由场景层位表传入）
#   ⇒ `PROTOCOL_FILE` / `POSITIONS_FILE` 两个常量**已删**；原版的协议漂移闸整块已去。

# ★★★ 启动即建两个目录（★ 用户面检查报告 P1-2）。
#   ★★ 为什么必须在这里建、而不是等写账时懒建：
#     · 《先读我》§五的目录树里**画了** `data\` 与 `history\` ⇒ ★ 用户解压后会去找；
#     · 用户**不双击 bat、直接 `python app\server.py`** ⇒ `启动.bat` 那两句 `mkdir` **被跳过** ⇒
#       ★ 目录不存在 ⇒ ★ 而且"要到第一次存账才报错"，**属于坏得看不出来**。
#   ★ 一次性建齐（★ 与 bat 那句是**同一个效果**，不是第二处真值 —— 目录名只有这两个地方写，
#     且两边都指向 `DATA_DIR` / `APP_DIR.parent / "history"` 这两个常量）。
for _d in (DATA_DIR, APP_DIR.parent / "history"):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception as _e:
        print("[dir] ★ 建目录失败 {}：{}".format(_d, _e), file=sys.stderr)


# ★ 本外发版：首页**就在本目录**（`app\index.html`）—— ★ 原版把首页放在 `shell\` 下，本版扁平。
INDEX_FILE = APP_DIR / "index.html"

HOST = "127.0.0.1"
# ★ 若这个端口也被占：★ 设环境变量 `ROOTTHINK_PORT`（例：`set ROOTTHINK_PORT=9000`）再启动。
#   ★ 走环境变量是**唯一推荐**的路 —— ★ `app\` 这一层升级时会被整包替换，改这里会丢。
PORT = int(os.environ.get("ROOTTHINK_PORT") or "8394")
HISTORY_TURNS_LIMIT = 24  # 送入上下文的最大历史轮数（一问一答算一轮）

# ★★ 检索轮的两个上限（2026-10-06 加 · 全面检查时发现这里有两个不同的字面量 `3` 与 `5`，且注释与代码不符）
#
#   ⚠️ 原状：`use_tools = tools if tool_rounds < 3 else None  # 最多 3 轮检索`
#            `if tool_rounds > 5: break`
#      ⇒ 两个**不同**的数、都写死，第二个的用意没写出来 ⇒ 读的人会以为其中一个是错的。
#
#   ★★ 而查清后要如实说：**它们本是两件事，但第二个现在够不着。**
#     因为 `tool_rounds` **只在"这一轮真有 tool_calls"时才 +1**（见下面 `if not round_calls: break`）
#     ⇒ 不带工具的轮**根本不计数**。故：
#        ① `MAX_TOOL_ROUNDS`   —— **真正起作用**：允许**带工具**的轮数（之后强制收束）
#        ② `MAX_ROUNDS_HARD_CAP` —— **现在够不着的**防跑飞硬闸（12 > 3 ⇒ 第①条总是先触发）
#     ★ 保留 ② 的理由：它是**兜底**，不是活逻辑 —— 将来若改 ① 的语义（例如给"总轮数"也计数），
#       ② 就是那道闸。**但必须写明它现在够不着**，免得下一个人以为它在生效。
MAX_TOOL_ROUNDS = 3          # ① 最多 3 轮带工具（**生效中**）
MAX_ROUNDS_HARD_CAP = 12     # ② 防跑飞硬闸（★ 2026-10-08 起**真正可达**：见下）
#: ★★★ 2026-10-08 加（依持有方实测：台窗一轮连翻 5 次目录 · 129k token · 卡住）：
#:   ★★ 诊出的两个缺口（都在这两行之上）：
#:     ① **每轮工具调用次数无上限** —— `for i, sc in sorted(round_calls.items())` 对
#:        `round_calls` 不设限 ⇒ 模型一轮可声明任意多个 ⇒ 5 次列目录就是这么来的。
#:     ② **上界后只是"不再下发工具定义"** —— `use_tools = None`，而 `round_calls` 仍被
#:        **无条件收割**（模型能从历史里看到工具定义）⇒ 它仍可声明 tool_calls ⇒
#:        **照常执行** ⇒ 循环不 exit ⇒ `tool_rounds` 继续 +1 ⇒ ★ **`MAX_ROUNDS_HARD_CAP`
#:        其实是够得着的**（原注释说"够不着"，那是**只看 `use_tools`、没看收割路径**）。
#:   ★ 故本条加两道硬闸：**每轮上限** + **上界后拒绝执行**（见 `_TOOL_ROUND_CAP` 与派发处）。
MAX_TOOL_CALLS_PER_ROUND = 3  # ① 每轮最多 3 次工具调用（★ 超出的**不执行**，回一句说明）


#: ★ 通过项：密钥只从环境读。这个名字就是契约。
KEY_ENV = "DEEPSEEK_API_KEY"


def _load_dotenv_local() -> dict:
    r"""★★★ 让**本服务自己**读 `.env.local`（2026-10-08 加 · 治"能力面随谁起它而变"）。

    ★ 为什么必须由服务自己读（★ 这是 2026-10-08 一次真事故的根因）：
      · 2026-10-07 18:45 的安全加固把三枚 key **从注册表搬进 `.env.local`**（ACL 收紧）；
      · 而**只有 `启动.bat` 会读它** —— ★ 一旦服务由**别的链**（如 DeepSeek Harness）拉起，
        就**拿不到 `TAVILY_API_KEY`** ⇒ `search.enabled=false`，★ **而聊天照常**（因为那条链自带
        `DEEPSEEK_API_KEY`）⇒ ★★ **同一个 8390，能力面随"谁起它"而变**。
      · ★ 这不是"加固弄坏了功能"，是"**加固改了 key 的存法，而启动方没跟着改**"。

    ★ 读法：`KEY=VALUE` · `#` 注释 · 容许引号包裹（★ 就贴在等号右边，不要加空格）。
    ★ 优先级：★ **已存在的环境变量优先（不覆盖）** —— 以便临时覆盖调试，★ 也与旧行为一致。
    ★ 失败/缺失：★ **不抛**，★ 但**打印一行**（★ 不许静默）。
    """
    out = {}
    # ★★ 本外发版：只读**根目录**那一份（与 app\ 同级）——
    #    ★ 为什么不是 `APP_DIR / ".env.local"`：★ `app\` 是**整包替换式升级要覆盖的那一层**，
    #      ★ key 住在里面 ⇒ 升级会把使用者的 key 一起抹掉。★ 而根目录那份升级不碰。
    #    ★ 为什么**只**读一份：★ 两份就会漂（★ 改了这份、读的是那份，且没有任何提示）。
    f = APP_DIR.parent / ".env.local"
    if not f.exists():
        return out
    try:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            k, v = k.strip(), v.strip()
            if not k:
                continue
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            out[k] = v
    except Exception as e:                                      # noqa: BLE001
        print("[env] ⚠️ 读 {0} 失败：{1}".format(f.name, e), flush=True)
        return {}
    return out


_DOTENV = _load_dotenv_local()
if _DOTENV:
    _added = []
    for _k, _v in _DOTENV.items():
        if os.environ.get(_k):
            continue                       # ★ 已存在 ⇒ 不覆盖（临时覆盖调试仍可用）
        os.environ[_k] = _v
        _added.append(_k)
    # ★ 只报**名字**，绝不回显值
    print("[env] 从 .env.local 补入：{0}".format(", ".join(sorted(_added)) or "（无新增）"), flush=True)
else:
    print("[env] ★ 未找到或未读到 .env.local —— ★ 把同目录的 `_env.example` 复制成 `.env.local`、"
          "填上 KEY、重启；★（没 key 时界面照常打开，★ 但一发问就会明确拒服务 —— 不静默）",
          flush=True)


DEFAULT_CONFIG = {
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-chat",  # 稳定别名；V4 系列按官方模型名在设置里改
    "temperature": 1.0,
    "max_tokens": 4096,
}

# ★★ 不许出现在配置文件里的形态（机检：把纪律变成检查）
#: ★★ 2026-10-28（依 D 第 17 轮 P0-3）：此前是 (sk-, api_key)。
#:   get_api_key() 的第二路就在读 config.local.json 的 api_key（界面存 key 的正路），
#:   而这段判定把它当「老版本残留」⇒ /api/health 每次都说「该字段已被本版忽略，请删除」。
#:   ★★★ 而「已被忽略」是假话 —— 用户照 hint 删掉字段 ⇒ key 就丢了。
#:   ★★ 修法（D 给的二选一，取第一）：合法化 config 路 ⇒ api_key 不再是残留；
#:   只有真正的 key 本体（sk- 前缀）出现在**非 api_key 的字段**里才算脏。
KEY_LIKE = ("sk-",)


# ---------------------------------------------------------------- 配置
def load_config() -> dict:
    """★ 只读**非敏感**配置。

    ⚠️ 若 `config.local.json` 里仍残留 key（老版本会写进去），**本函数不静默忽略** ——
    它在 `CONFIG_FILE_TAINTED` 里留一个标记，由 `/api/health` 与启动横幅显形。
    """
    cfg = dict(DEFAULT_CONFIG)
    tainted = False
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        if isinstance(raw, dict):
            # ⚠️ 检出残留 key：**不删它**（改文件是持有方的事），但**不采用**它，且记下来
            if any(k in raw for k in KEY_LIKE):
                tainted = True
            for f in DEFAULT_CONFIG:
                if f in raw:
                    # ★★★ 2026-10-28（依 D 第 17 轮 P0-1）：`base_url` 必须过同一道白名单。
                    #   ★ 别的字段照收；只有 base_url 不合法时**回落到默认值**并留痕。
                    if f == "base_url" and not _base_allowed(str(raw[f])):
                        cfg["base_url"] = DEFAULT_CONFIG["base_url"]
                        cfg["_base_url_rejected"] = str(raw[f])
                        continue
                    cfg[f] = raw[f]
    return cfg, tainted


def save_config(cfg: dict) -> None:
    """★ 只写**非敏感**字段 —— 这是双保险：即使上游误传了 key，也不落盘。"""
    clean = {k: v for k, v in cfg.items() if k not in KEY_LIKE}
    CONFIG_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")


def get_api_key() -> str:
    """三路取 key —— 优先级：环境变量 ⇒ config.local.json ⇒ .env.local。

    ★★★ 2026-10-28（丙）：此前这里只读环境变量。那条铁律的理由是
      「通过项不得由 HTTP 填」—— 而本版给 POST /api/key 加了本机令牌闸
      （没有它任意网页能换 key），故那条理由不再成立；
      而只读环境变量反而造出一个更坏的东西：
      界面存了 key 而引擎读不到 ⇒ 界面报「已保存」，而 /api/chat 仍报「未配 key」。
      ★★★ 那正是「存了而不生效」—— 同本体系记过多次的那种。
    ★★ 而环境变量仍然优先（故它盖不过环境变量，POST /api/key 会如实回报「改不了」）。
    """
    k = (os.environ.get(KEY_ENV) or "").strip()
    if k:
        return k
    if CONFIG_FILE.exists():
        try:
            v = str(json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("api_key") or "").strip()
            if v:
                return v
        except Exception:                                                # noqa: BLE001
            pass
    ef = APP_DIR.parent / ".env.local"
    if ef.exists():
        try:
            for ln in ef.read_text(encoding="utf-8", errors="replace").splitlines():
                if ln.strip().startswith(KEY_ENV + "="):
                    _v = ln.split("=", 1)[1].strip()
                    return _v.strip('"').strip("'")
        except Exception:                                                # noqa: BLE001
            pass
    return ""


# ★★★ 2026-10-28（A 修）：这一行原本在 `get_api_key()` 后面（改前）。
#   而我把它改成三路读时，用「下一个 `def`」做截断边界 ⇒ **这行不以 `def` 开头，被吞了**
#   ⇒ `CONFIG` 与 `CONFIG_FILE_TAINTED` 全未定义，服务起不来（`NameError`）。
#   ★ 它和今晚记过多次的那个形态同形：**用"边界"做截断，而边界内还有别的东西**。
#   故这里补回来，且位置不变（`get_api_key` 之后、`_egress_log` 之前）。
CONFIG, CONFIG_FILE_TAINTED = load_config()


#: ★★★ 2026-10-28（依 D 第 17 轮 P1-1）：此前 _egress_log 里用了 EGRESS_FILE
#:   而**全仓零定义** ⇒ 每次抛 NameError，被它自己的 except Exception: pass 吞掉。
#:   ★★ 实测：两轮对话 + 一次连通性自检全部真实出网，而 data/ history/ 里
#:   **没有任何出网账文件** —— 一个自称「唯一可对账处」的函数，一行不写、零告警。
#:   ★★★ 故这里补上定义。append-only JSONL，在 history/ 下（git 忽略）。
EGRESS_FILE = APP_DIR.parent / "history" / "egress.jsonl"


def _egress_log(dest: str, note: str, approx_bytes: int = 0) -> None:
    """出网记账：每次对外 HTTP 请求落一行（append-only；记账失败不影响主流程）。

    ★★ 本外发版改（★ 原版这里还有一段"同步写链"）：★ **写链部分已去** ——
       ★ 那条链属于**更完整的内部版本**，★ 外发包里没有它。
    ★★★ 2026-10-28（依 D 第 17 轮 P1-3）：本函数外那两处 `print(..., file=_sys.stderr)`
      用的是 `_sys`，而 `_sys` 只在 `atomic_io` 导入**失败**的分支里定义 ⇒
      主路径上 `NameError`，且 except 体里又用一次 ⇒ **二次 NameError ⇒ chat 端点 500**。
      修法：全文件改回标准库 `sys`（★ 已在本轮一并替换）。
       ★ 而本函数**保留** —— ★ 它答的是「**这一轮到底出网了没有**」（★ 唯一可对账处的一部分）。
    """
    try:
        EGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "dest": dest,
               "note": note, "approx_bytes": approx_bytes}
        with open(EGRESS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass





def _strip_think(text: str) -> str:
    """历史轮里的重档思考块不回灌上下文（省 token；行使史原文不受影响）。"""
    out = re.sub(r"<think>[\s\S]*?(?:</think>|$)", "", text).strip()
    return out or text





# ---------------------------------------------------------------- 协议


# ══════════════════════════════════════════════════════════════════
# ★★★ 场景层位表（★ 本外发版**唯一的产品定义** · ★ 它是"协议正文"）
#
#   ★★ 为什么读它而不是自带那份 91 KB 协议（★ `loop.py:134` 逐字）：
#      「`protocol_text` —— ★ **直接用一段文本当协议正文**（★ 业务方不必先把它落成文件）。
#        ★★ 传了它 ⇒ 优先于 `protocol_file`。★ **这是"换掉协议就换掉产品"那个机制的接口形态。**」
#   ★★★ 故"只带一份 ≤3 KB 的场景层位表"**不需要写任何新代码** —— 传一个参数即可。
#
#   ★★★★ 相位指纹（★ 2026-10-12 加 · ★ 出处：A 的《核对·最精简版与相干波束》§1.3 处方）：
#      ★ 它是**那份层位表的 sha256 前 8 位**，★ 而它进**凭据行第③样**。
#      ★★ 为什么：★ 任意两个使用者的输出一摆在一起，★ **就能判"我们是不是同一相位"** ——
#         ★ 而"同一个相位规则"正是**相干的最小可判条件**。
#      ★（体系那边有一句：★ 波束不是一个东西，是关系；★ 而关系要可判，★ 先要有可比的指纹。）
# ══════════════════════════════════════════════════════════════════
_PROTO_FILE = APP_DIR / "protocol" / "拆解器·协议.md"
# ★ [收尾净化 2026-10-13]（★ 敌手D 第10轮 V-4）：★ 这里原有一段生成器自用的路径
#   与一个死变量（生成器语境、在产物里**恒不被引用**）—— ★ 已整块删除：
#   ★ 在产物里 `APP_DIR` 指向正确，那段注释描述的坑不存在 ⇒ 死代码 + 假陈述 + 内部自曝。


def _parse_protocol(text):
    """★ 解析协议正本：按 @@@NAME@@@ 分区取块（★ 单一定界，无歧义）。

    ★★ 归拢（2026-10-12）：★ 原先协议散在 场景·看清问题.json + 本文件常量里两处；
      ★ 现在**真值只有一处** = protocol/拆解器·协议.md（★ 人类可读 · 可换 · 可对账）。
    ★★ 本段在单引号替换块内，故：换行一律用 chr(10)、反斜杠用 chr(92) —— ★ 不写裸反斜杠与裸反引号。
    """
    import re as _re
    _nl = chr(10)
    _pat = ("@@@([A-Z_]+)@@@[^" + _nl + "]*" + _nl + "(.*?)(?=" + _nl +
            "@@@[A-Z_]+@@@[^" + _nl + "]*" + _nl + "|" + chr(92) + "Z)")
    _out = {}
    for _m in _re.finditer(_pat, text, _re.S):
        _out[_m.group(1)] = _m.group(2)

    def _items(_name):
        return [_ln[2:] for _ln in _out[_name].split(_nl) if _ln.startswith("- ")]

    return {"相位规则": _out["PHASE_RULES"], "层位表": _out["SCENE_TABLE"],
            "场景纪律": _items("SCENE_RULES"), "追加纪律": _items("SCENE_EXTRA_RULES"),
            "失效处理": _items("FAILURE"), "落款判据": _items("CRITERIA"),
            "落款": _items("FOOTER")}


try:
    _PD = _parse_protocol(_PROTO_FILE.read_text(encoding="utf-8"))
    # ★★★★★ 2026-10-12 改（★ 出处：持有方追问「相位指纹是什么」+ A 的《判断·护根该不该是唯一档位》）：
    #   ★ 原先：`SCENE_PROTOCOL = 层位表` · ★ `PHASE_FP = sha256(层位表)[:8]`
    #     ⇒ ★★ **两个毛病**：
    #       ① ★ **换场景 ⇒ 指纹变**（★ 不对 —— ★ 同一条相位下可以有多个产品）；
    #       ② ★ 三条相位规则里只有"可停"进了层位表 ⇒ ★ **改协议里的「可再选」，指纹不会变**（★ 名不副实）。
    #   ★★ 现在分开：
    #     · `PHASE_RULES`   = 「相位规则」那一段（★ **所有节点共有** ⇒ 常量）
    #     · `SCENE_TABLE`   = 「层位表」那一段（★ **这个产品**的定义 ⇒ 变量）
    #     · `PHASE_FP`      = **只算 `PHASE_RULES`** ⇒ ★ **换场景不变、改规则才变**
    #     · `SCENE_PROTOCOL`= 两者相接 ⇒ ★ **都进提示词**（★ 而只有前者进指纹）
    PHASE_RULES = str(_PD["相位规则"] or "")
    SCENE_TABLE = str(_PD["层位表"])
    SCENE_PROTOCOL = (PHASE_RULES + chr(10) + SCENE_TABLE) if PHASE_RULES else SCENE_TABLE
    SCENE_RULES = [str(x) for x in _PD["场景纪律"]]
    _EXTRA_RULES = [str(x) for x in _PD["追加纪律"]]
    _FAILURE = [str(x) for x in _PD["失效处理"]]
    _CRITERIA = [str(x) for x in _PD["落款判据"]]
    _FOOTER_TPL = [str(x) for x in _PD["落款"]]
    # ★ 相位指纹 = **相位规则**的 sha256 前 8 位（★ 不是整张层位表）
    #   ★ 缺「相位规则」⇒ 如实置 None（★ 不编一个 —— ★ 那会让"没有相位"看起来像"有相位"）
    PHASE_FP = hashlib.sha256(PHASE_RULES.encode("utf-8")).hexdigest()[:8] if PHASE_RULES else None
    SCENE_FP = hashlib.sha256(SCENE_TABLE.encode("utf-8")).hexdigest()[:8]
    if PHASE_FP:
        _FOOTER = [x.replace("{{PHASE_FP}}", str(PHASE_FP)) for x in _FOOTER_TPL]
    else:
        _FOOTER = [x.replace("{{PHASE_FP}}", "<无法判>") for x in _FOOTER_TPL[:-1]]
except Exception as _e:                                          # noqa: BLE001
    PHASE_RULES, SCENE_TABLE, SCENE_PROTOCOL, SCENE_RULES = "", "", "", []
    _EXTRA_RULES, _FAILURE, _CRITERIA, _FOOTER = [], [], [], []
    PHASE_FP, SCENE_FP = None, None
    print("[scene] ★ 协议正本载入失败（{0}: {1}）—— ★ 不静默：本服务仍起，但约束会缺层位表".format(
        type(_e).__name__, _e), file=sys.stderr)

#: ★ 追加进约束的段落（★ 走 `loop.build_system_prompt` 的 `extra_sections` 口）
#:   ★★ 位置是有意的：★ 它进得来，★ 但**盖不掉**后面的常量块闸与回流（★ `loop.py:177` 逐字）。
#:
#: ★★★★ 2026-10-12 加：**守根应变四条**（★ 出处：A 的《调整建议·拆解台能不能更人性化》）
#:   ★ 起因：★ 一份 12 条的真实导出里，六轮同一形状（复述 → 有几面 → 三条路 → 指出对方在回避 → 格言）。
#:   ★★ 那六条**一条都没违反守根**，★ 而合起来"不像人" —— ★ 因为**它们把守根演成了固定程式**。
#:   ★★★ 故本四条**不放松任何一条约束**，★ 只规定"**怎么读**"：
#:     ① 说不完整 ⇒ ★ **禁暗示**（暗示会变成被审视）· ② 一轮一件结构件 + 禁连续同形
#:     ③ 对"对方"的观察最多一次 · ④ 真问题时内容面不少于一半。
#:   ★★★★ **顺序有意**：★ 读法在前、落款在后 ⇒ ★ 落款仍是**最后一句**（★ 不许被读法挤走）。
SCENE_EXTRA = list(SCENE_RULES) + _EXTRA_RULES + _FAILURE + _CRITERIA + _FOOTER



#: ★★★★ **档位真值只在这一行**（★ 本外发版的核心约束）。
#:
#:   ★ 为什么要有 `TIER_MODE` 这个名字（★ 而不是各处直接写 `"light"`）：
#:     ★ 档位字面量原本在**四处**被写死（提示词委托 · 账 user 轮 · 账 assistant 轮 · 判据记账）
#:     ⇒ ★★ 那就是**四个会漂的地方**（改了这处、忘了那处 ⇒ 账里记的与真正跑的不是一回事）。
#:   ★★ 故：★ **真值只写在这里**，其余三处**引用它** ⇒
#:     · 字面量写入点 == 1，★ 是**能数出来的形状**；
#:     · 而账里那条 `mode` **不可能**与真正跑的档位不一致。
#:
#:   ★★★★ 2026-10-12 改：★ **护根不再是模块级常量** —— 它**每轮由请求带来**。
#:     · `TIER_MODE`  = `"light"`   —— ★ **本版仍只有轻档**（★ 重档那条分支已整块删）
#:     · `protector`  —— ★ **请求级**（★ `ChatIn.protector` · ★ 默认 `False` 即工作模式）
#:     ★★ 为什么这样不违反"一处真值"：★ 真值是**一处**（`ChatIn.protector` 那一个字段），
#:        ★ 而它**每轮落账** ⇒ ★ **"防漂"要的是"真值唯一且可对账"，★ 不是"值恒定"。**
#:     ★★★ 而"护根只能由用户**显式**开"这条**没有被放松**：
#:        ★ 默认 `False` · ★ 没有任何路径能**替用户**打开它。
TIER_MODE = "light"


# ★★★ 2026-10-09 本项目拆出：★ 判据/回流的**可复用部分**搬进 `core/loop.py`
#   （★ 那个更完整版本里的 `server.py` **一字未动**）
#   为什么：★ `server.py` 第 31 行起就是 `httpx`/`fastapi`/`uvicorn`/`pydantic`
#   ⇒ ★★ 只想用那 86 行回流，也得装整套 HTTP 栈。
#   ★ 故本处**委托** —— ★ **一处真理，两处使用**（本文件是服务端 · `loop.py` 是给业务方的裸核心）。
def _classify_uncomputable(dt: str) -> str:
    """★ 委托 `loop.classify_uncomputable`。"""
    import loop as _loop
    return _loop.classify_uncomputable(dt)


def _last_round_feedback(session_id: str = "") -> str:
    """★ 委托 `loop.last_round_feedback` —— ★ 核心四件的第 ④ 件（回流）。

    ★★ 注意：本函数**不传 `rows`** ⇒ `loop` 会自己 `import session_log` 取账
        （★ 与原实现同一条路；★ 也就是说那个"两处静默默认参数"的行为**保持不变**）。
    """
    import loop as _loop
    return _loop.last_round_feedback(session_id)
# [fs-feedback:END]


def build_system_prompt(session_id: str = "", protector: bool = False,
                        乱纪律: list | None = None,
                        return_breakdown: bool = False):
    """★ 委托 `loop.build_system_prompt` —— ★ 核心四件的第 ① 件（层位提示）。

    ★★★ **档位真值只在一处**（★ `TIER_MODE = "light"` 是模块级 · ★ `protector` 是请求级）：
        · `TIER_MODE`        = `"light"`  —— ★ 只有轻档（★ `loop.py` 里那条重档分支**已整块删**）
        · `protector`        —— ★★ **请求级**（★ `ChatIn.protector` · ★ 默认 `False` = 工作模式）
        ★★ 护根**只能由用户显式开** —— ★ 依装载件 `:509`「★ **护根模式（用户说出「进入护根模式」）**」
        ★★★ 而它**每轮落账** ⇒ ★ 防漂要的是"真值唯一且可对账"，★ **不是"值恒定"**。
        ★★ 这里**只是引用**，不写字面量 —— ★ 免得出现"第二个会漂的地方"。
    ★★★ 协议正文由 `protocol_text=SCENE_PROTOCOL` 传入（★ 2026-10-12 起 = **相位规则（三条·逐字）+ 层位表**）；
        场景纪律由 `extra_sections=SCENE_EXTRA` 传入（★ 含落款格式与相位指纹）。
    ★★ 三个注入点：★ **本版一个都不传** ——
        ★ `const_block`（原 §5.3 常量块闸）· ★ `search_cfg`（检索）· ★ `can_read_fs`（读文件）
        ★★ 三者的**来源**（那个"底" · 联网 key · 可读根）本外发版**都没有** ⇒ 一并去掉，
           ★ 免得提示词里出现三段与"帮人看清问题"无关的、恒报"无法判"的段。
    ★★ 凭据第③样由 `extra_sections` 里的**相位指纹**承担（★ 见上面的场景段）。
    ★★ `return_breakdown=True` ⇒ 返回 `(prompt, breakdown)`（★ 供下面那段预算读数用）。
        ★ 为什么要这个参数（★ 本外发版加 · ★ 原版的 chat 路径**没有**它）：
        ★★ 原版的预算读数段**自己又重建了一次**提示词（且**不传场景层位表**）——
            ★ 于是它量的是**另一个提示词**：★ 90 KB 协议那份（★ 或直接报错）
            ⇒ ★★ **读数是假的**，而它照样打印 ⇒ ★ 而 52,844 那个数**本来就是这个病**。
        ★ 正解：★ **一次构建、同一个对象** —— 真提示词与它的分段读数**同源**（不能有两个）。
    """
    import loop as _loop
    # ★★★★★ 三个来源，**顺序有意**（★ 各自的证据强度不同，★ 后来的更具体）：
    #   ① `SCENE_EXTRA`  —— 场景固有纪律（★ 每轮都在）
    #   ② `_形状纪律`     —— 上一轮**形状**读数（★ 治"合规的重复"）
    #   ③ `乱纪律`        —— **本轮输入侧**读数（★ 由调用方算好传进来 · ★ 见生成脚本 ⑤a-6）
    #   ★★★ 而**证据从哪来**要分清 —— ★ 两件不同的事，★ 不许互相顶替：
    #     · ② 读的是**上一轮的输出形状**（★ 看账即得）
    #     · ③ 读的是**这一轮的用户输入**（★ 只有调用方手上才有原文 ⇒ ★ 故由它算、传进来）
    #   ★★ 为什么 ③ 不在这里自己算：★ **本函数只拿得到 `session_id`**，★ 而用户原文
    #     **不落盘**（★ 账里只存 `材料指纹` · ★ 那是有意的）⇒ ★ **这里算不出来。**
    extra = (list(SCENE_EXTRA) + _形状纪律(session_id) + list(乱纪律 or []))
    out = _loop.build_system_prompt(TIER_MODE, bool(protector), session_id,
                                    protocol_text=SCENE_PROTOCOL,
                                    extra_sections=extra,
                                    return_breakdown=return_breakdown)
    return out


#: ★★★★ 轮形状（★ 本外发版加 · ★ 见生成脚本 ⑤a-2 那段注释）
#:   ★ 四类形状 —— ★ 判据只认**明确的结构标记**，★ 不猜语气、不猜长度。
#:   ★★ 为什么要它：★ 一段 12 条的真实对话里，六轮**同一形状**（复述→有几面→三条路→指回避），
#:      ★ 而**每一轮单看都合规**。★ 那种"合规的重复"只能由**看到上下文的一方**来发现。
_SHAPE_分面 = "分面"
_SHAPE_路 = "给路"
_SHAPE_追问 = "追问"
_SHAPE_直答 = "直答"


def _形状(reply_text: str) -> str:
    """★ 从回答正文判**本轮形状**（★ 只用明确标记；★ 判不出 ⇒ 直答）。"""
    t = reply_text or ""
    has_面 = ("一面是" in t) or ("另一面" in t) or ("还有一面" in t)
    has_路 = ("三条路" in t) or ("两条路" in t) or ("一条路" in t) or ("几条路" in t)
    if has_面 and has_路:
        return _SHAPE_分面 + "+" + _SHAPE_路
    if has_面:
        return _SHAPE_分面
    if has_路:
        return _SHAPE_路
    if "？" in t or "?" in t:
        return _SHAPE_追问
    return _SHAPE_直答


def _上一轮形状(session_id: str) -> str:
    """★ 读**本会话上一轮**的形状；★ 缺 ⇒ 空串（★ 不编一个默认值）。"""
    if not session_id:
        return ""
    try:
        import session_log as _sl
        cur = [r for r in _sl._rows() if r.get("session") == session_id]
        return str((cur[-1] or {}).get("形状") or "") if cur else ""
    except Exception:                                        # noqa: BLE001
        return ""


def _形状纪律(session_id: str) -> list:
    """★ 若上一轮与本轮**可能同形** ⇒ 注入一条明令（★ 否则不注入 —— ★ 不占篇幅）。"""
    prev = _上一轮形状(session_id)
    if not prev:
        return []
    return [
        "★★★ **服务端读数（不是你的自评）**：★ 你**上一轮**的输出形状是「{0}」。"
        "★ 那一轮单看合规，★ 而**同样的形状连着出现就是模板** —— ★ 故本轮**换个形状**：".format(prev),
        "   · 上一轮若**分过面** ⇒ 本轮**不要**再用「一面是…另一面是…」，★ 直接说人话；",
        "   · 上一轮若**列过路** ⇒ 本轮**不要**再列「三条路」，★ 该给就给、该停就停；",
        "   ★ **这一条不由你判断（你看不到历史）** —— ★ 你只管本轮不用上面那个形状。",
    ]


# ---------------------------------------------------------------- 会话
def _load_sessions() -> dict:
    if SESSIONS_FILE.exists():
        try:
            return json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
        except Exception as _e:
            # ★★★ 2026-10-13 安全修（★ 攻击演练 E·P2-2）：★ 损坏不许静默 ——
            #   ★ 静默返回空库 ⇒ 下一次保存把旧账全量覆盖（★ 归档兜底在，★ 但"静默"违自家 fail-closed）。
            print("[会话账] ★ sessions.json 读取失败（{}: {}）—— 返回空库；旧账有归档兜底".format(
                type(_e).__name__, _e), flush=True)
    return {"sessions": []}


def _save_sessions(db: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    # [atomic-replace] ★ B-37：改用原子替换（原本是 write_text 全量覆盖，写一半崩就毁整本）
    # ★★★ 2026-10-09 本项目加（★ 记忆机制落点二 · ★ 见 `core/archive.py` 的头注）：
    #    ★★ 原子替换只保证「要么新、要么旧」—— ★ **它不保留旧的**。
    #    ⇒ ★ 故在覆盖**之前**先另存一档（★ **只增、永不覆盖** · ★ 台账 append-only）。
    #    ★★ 而**归档失败不许挡住保存**（★ 保存是主路；★ 归档是兜底）——
    #       ★ 但**也不许静默**：★ 失败时打一行到 stderr（★ 含原因）。
    try:
        import archive as _ar
        # ★ 本外发版：★ **没有现役件就不调归档器**（★ 第一轮本来就没有"上一档"可存）。
        if SESSIONS_FILE.exists():
            _ok, _det = _ar.archive(SESSIONS_FILE, why="每轮全量保存前的兜底归档")
            if not _ok:
                print("[archive] ★ 归档未成：{0}".format(_det), file=sys.stderr)
    except Exception as _e:                                              # noqa: BLE001
        print("[archive] ★ 归档不可用：{0}: {1}".format(type(_e).__name__, _e), file=sys.stderr)
    atomic_io.write_json_atomic(SESSIONS_FILE, db, indent=1)


def _find_session(db: dict, sid: str):
    for s in db["sessions"]:
        if s["id"] == sid:
            return s
    return None


# ---------------------------------------------------------------- API
app = FastAPI(title="rootthink")

# ---------------------------------------------------------------- 本机凭据闸
#: ★ 启动时生成、**只打印在控制台**、只存内存。前端由 `/` 注入 meta 后带上。
#: 它不是"认证用户"，是**证明请求来自本机那份页面**（而不是别的网页）。
LOCAL_TOKEN = secrets.token_urlsafe(32)
TOKEN_HEADER = "x-rootthink-token"
ALLOWED_ORIGINS = {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}

#: ★★★ **Host 白名单的"本机名"部分**（★ 2026-10-09 晚加 · ★ 出处：★ 异源第二轮 §4/P0-3）。
#:
#:   ★★ 为什么要有它：★ 中间件的 Origin 检查挡得住"外来网页直接拉它"，
#:      ★★★ **但挡不住 DNS 重绑定** —— 攻击者把自己的域名解析到 `127.0.0.1`，
#:      ★★ 于是浏览器认为"来源就是这个 origin" ⇒ **它自己的 Origin 检查被绕过。**
#:   ★★ 而 Host 头**骗不了**：★ 重绑定请求的 `Host` 是**攻击者的域名** ⇒ ★ **一卡就断。**
#:
#:   ★★★★ **而它**不许写死端口****（★ 2026-10-09 晚 · ★ 我第一版就栽在这里）：
#:      ★ 我第一版写成 `{f"127.0.0.1:{PORT}", …}`（★ 用模块常量 `PORT`）⇒
#:      ★★ **我拿 `8399` 起它测试时，★ 连**正路**都被拒了（403）** ——
#:      ★★★ **而更坏的是：★ 那条错看起来像"闸生效了"**（★ 因为伪造 Host 也是 403）；
#:      ★★★★ **若我不跑正路，★ 我会以为它成功了。**
#:   ★★ 故这里只放**本机名**，★ 端口由 `_host_ok()` **按请求实际端口**补 ——
#:      ★ **这样"换个端口起"不会把服务锁死**（★ 而原项目的验证件正好用 `8399`）。
_本机名 = ("127.0.0.1", "localhost", "[::1]")

#: ★★ 兼容旧名（★ 若别处引用了它）：★ 只列**默认端口**那一组 —— ★ **而判据请用 `_host_ok()`。**
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"}


def _host_ok(host: str, req_port: str) -> bool:
    """★★★ 判 `Host` 头合不合法 —— ★ **按请求的实际端口**，★ 不按模块常量。

    ★★ 接受两种写法（★ 实测浏览器两种都发）：
       · `127.0.0.1:8390` / `localhost:8390` / `[::1]:8390`
       · 以及**不带端口**的 `127.0.0.1` / `localhost`（★ 标准端口时浏览器会省掉）
    """
    h = (host or "").strip().lower()
    if not h:
        return False
    for 名 in _本机名:
        if h == 名:
            return True
        if h == "{0}:{1}".format(名, req_port):
            return True
    return False


def _页头() -> dict:
    """★ 首页/配置页的响应头（★ 2026-10-09 晚加 · ★ 出处：★ 异源第二轮 §4/P0-3 判据 3）。

    ★★★ 两条 · ★ 而第二条**按实测裁的**（★ 不许照抄一个会破页面的 CSP）：
      · **`X-Frame-Options: DENY`** —— ★ 禁止被别站 `iframe` 嵌套
        （★ 实测：★ 本页面自己 **`iframe` / `window.top` / `window.parent` 各 0 处** ⇒ **禁了不破它**）；
      · **`Content-Security-Policy`** —— ★ 而它**必须放行 inline**：
        ★★ 实测本页面有 **1 个无 `src` 的 `<script>` · ★ 1 个 `<style>` · ★ 2 处 `on*=` 内联事件**
        ⇒ ★ **若写 `script-src 'self'` 而不带 `'unsafe-inline'`，★ 页面当场死。**
        ★ 而**外部资源为零**（★ 实测：无外部 `script` / 无外部 `link`）⇒ ★ `default-src 'self'` 足够。
      · **`connect-src`**：★ 实测页面只 `fetch('/api/health')`（★ 同源）⇒ ★ **`'self'` 够**
        （★ 而那一条若将来要打外站 API，★ **这里必须同步改** —— ★ 故我把这句写在注释里）。
    """
    return {
        "Cache-Control": "no-store",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self'; "
            "img-src 'self' data:; "
            "frame-ancestors 'none'; "
            "base-uri 'none'; "
            "form-action 'none'"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }


@app.middleware("http")
async def local_origin_gate(request, call_next):
    """★★ 两道闸，**默认拒绝**（fail-closed）：

    ① **Origin 闸**：带了 `Origin` 而**不是本服务自己的来源** ⇒ 直接 403。
       · 浏览器对**跨站**请求一定会带 `Origin` ⇒ 恶意网页在这一步就被挡住。
       · ★ **没有 `Origin` 的一律放行**（curl / 本机脚本 / 同源导航）—— 那不是"网页攻击"这一路。
    ② **Token 闸**：除 `/` 与 `/api/health` 外，**都要** `X-Rootthink-Token`。
       · ★ 恶意网页即便绕过 Origin（例如用户禁用了该头），**也读不到页面里的 token**（跨站读被 CORS 挡）。
    """
    origin = request.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        return JSONResponse({"detail": "跨站请求被拒（Origin 不在白名单）"}, status_code=403)

    path = request.url.path
    # ★★★ **Host 闸**（★ 2026-10-09 晚加 · ★ 出处：★ 异源第二轮 §4/P0-3）——
    #   ★ 放在中间件里 ⇒ ★ **它覆盖所有路径**（★ 不只 `/`），★ 且**按请求实际端口**判
    #   （★ 故换端口起服务不会把正路锁死 —— ★ 那是我第一版栽的坑）。
    #   ★★ 治的是 **DNS 重绑定**：★ 中间件的 `Origin` 检查挡不住它
    #   （★ 重绑定后浏览器认为"来源就是这个 origin"），★ 而 **`Host` 头骗不了**。
    if not _host_ok(request.headers.get("host", ""), str(request.url.port or "")):
        return JSONResponse(
            {"detail": "Host 不在白名单（★ 本服务只服务本机）"}, status_code=403)

    # ★ `/` 也要求**同源** —— 否则任意网页能拉着本服务吐页面（页面里带 token）。
    #   它读不到响应（跨站读被 CORS 挡），但**不吐**比"吐了读不到"更硬。
    if path == "/" and origin is not None and origin not in ALLOWED_ORIGINS:
        return JSONResponse({"detail": "跨站请求被拒"}, status_code=403)

    if path != "/" and path != "/api/health":
        if request.headers.get(TOKEN_HEADER) != LOCAL_TOKEN:
            return JSONResponse(
                {"detail": "缺少或错误的 X-Rootthink-Token —— ★ 请从本服务打开的页面访问。"},
                status_code=403,
            )
    resp = await call_next(request)
    # ② 附带的 CORS 钳制：只允许本来源读
    if origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, " + TOKEN_HEADER
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    return resp


NO_KEY_MSG = (
    "未配置 API Key。\n"
    "★ 怎么填（推荐 · 一次填好、以后升级也不丢）：\n"
    "  1) 把本目录的 `_env.example` 复制一份，改名成 `.env.local`；\n"
    "  2) 打开它，在 `{0}=` 后面贴上你的 key（形如 sk-...），保存；\n"
    "  3) 回启动窗口，**关掉再双击一次 `启动.bat`**。\n"
    "★ `.env.local` 必须和 `启动.bat` 放在**同一层**（★ 不要放进 `app\\` 里）。\n"
    "★ 也可以设系统环境变量 `{0}`（在终端里 `set {0}=sk-...` 再重启）——\n"
    "  但那个只在**当前窗口**有效，关掉就没了；且界面**不会**写、**不会**存 key（这是有意的）。"
).format(KEY_ENV)


class ConfigIn(BaseModel):
    api_key: str | None = None      # ★ 收到即拒（保留字段只为给出清楚的报错）
    base_url: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class SessionIn(BaseModel):
    title: str | None = None


class ChatIn(BaseModel):
    # ★★★★ 2026-10-12：★ **档位恢复为请求级**（★ 真值就在这一处 · ★ 每轮落账）。
    #   · `mode`      —— ★ **锁在 `"light"`**（★ 本版只有轻档 · ★ 重档那条分支已整块删）
    #   · `protector` —— ★★ **默认 `False` = 工作模式**；★ 用户**显式**开才是护根
    #     ★ 依装载件 `:509` 逐字：「★ **护根模式（用户说出「进入护根模式」）**」⇒
    #       ★★ **它是一个动作，不是一个默认值。**
    #   ★ 而**不收 `doc_ids`** —— ★ 文档上传库整块已去（★ 依 A 核对件 §2.1 第 2 条）。
    session_id: str
    message: str
    protector: bool = False   # ★ 默认工作模式；用户显式开才是护根


@app.get("/")
def index(request: Request):
    """★ 注入本机 token（页面把它带在后续请求的头上）。

    ⚠️ 此处**必须**用 `HTMLResponse` 而非 `FileResponse` —— 后者会把文件原样发出，token 就进不去。

    ★★★ **2026-10-09 晚加两道**（★ 出处：★ 异源第二轮 §4/P0-3）：
      ★★ 异源逐字：★「★ **`GET /` 是 token 注射器** —— ★ 该页**免 token** 且注入**本进程活 token**」。
      ★★★ **而现值比它说的窄**（★ 我实测）：★ `:943` **已经**有一条同源检查 ——
        外来 `Origin` ⇒ **403**（★ 实测）⇒ ★ **"任意网页拉它吐页面"那半**已被挡住。**
      ★★ 而**它剩下的两条是真的**：
        · **① 无防嵌套头** ⇒ 别站可用 `iframe` 嵌它，★ 而**同源策略算那算同源**（★ 点劫持）；
        · **② 无 Host 校验** ⇒ ★★ **DNS 重绑定**能把外来站点的请求变成"同源"
          （★ 那时它自己的 Origin 检查**会被绕过**，★ 因为浏览器认为"来源就是这个 origin"）。
    """
    # ★★★ **Host 闸已移到中间件**（★ 2026-10-09 晚 · ★ 因为我第一版把它写在这里，★ 而**它用了模块常量 `PORT`**
    #   ⇒ ★★ **换端口（如原项目验证件用的 `8399`）就把**所有**请求都拒了** —— ★ 我实测到了那个
    #   （★ `GET /` 在 8399 上 403）。
    #   ★★★ **而更坏的是：★ 那条错看起来像"闸生效了"**（★ 因为伪造 Host 也 403）——
    #   ★★ **若我不看正路，★ 我会以为它成功了。**
    html = INDEX_FILE.read_text(encoding="utf-8")
    fe_ver = str(int(INDEX_FILE.stat().st_mtime))
    inject = (f'<meta name="rootthink-token" content="{LOCAL_TOKEN}">\n'
              f'<meta name="rt-fe-version" content="{fe_ver}">')
    if "</head>" in html:
        html = html.replace("</head>", inject + "\n</head>", 1)
    else:
        html = inject + "\n" + html
    return HTMLResponse(html, headers=_页头())


@app.get("/api/health")
def health(request: Request):
    """★★ B-39（v3.7 改）：**分两档回** —— 免 token 只给最小集。

    为什么：本端点是**唯一免 token 的**（中间件显式放行），
      而它原本回了 `has_key` / `key_source` / `can_write` / `write_roots` /
      `protocol_state` / `protocol_detail` / `search.provider` / `config_file_tainted`
      ⇒ ★ **未鉴权的任意本机进程都能读到本机配置面**。
      ★（A 核过：它**不含 key / token**，故暴露面本来就小；本次是**防未来**。）

    ★ 两档的分界：
      · **无 token** ⇒ 只回 `{{ok, app}}`（外部探活需要的就这两个）
      · **带正确 token** ⇒ 回全部诊断面（★ 故监控与自检**一样能用**，只是要带 token）
    ★ 不因此改中间件（否则 `/` 的同源规则会被连带弄乱）—— 判在本函数里。
    """
    _full = request.headers.get(TOKEN_HEADER) == LOCAL_TOKEN
    out = {"ok": True, "app": "拆解器（外发 · 最精简版）"}
    if not _full:
        out["detail"] = "★ 详情需 " + TOKEN_HEADER + "（从本服务打开的页面里取）"
        return out
    out.update({
        "ok": True,
        "app": "拆解器（外发 · 最精简版）",
        "port": PORT,
        "has_key": bool(get_api_key()),
        "key_source": "env:" + KEY_ENV,
        # ⚠️ 显形：老配置文件里仍有 key。**不阻塞启动**，但**每一轮都提醒**。
        "config_file_tainted": CONFIG_FILE_TAINTED,
        "tainted_hint": ("config.local.json 里有 **sk- 开头的字符串**出现在 `api_key` 之外的字段里"
                         "（★ 那才是真的脏）。`api_key` 字段本身是**合法的** —— "
                         "它是界面存 key 的正路，**不要删它**。") if CONFIG_FILE_TAINTED else "",
        # ★★ 档位（★ 本版加）：★ 这里报的是**可用的档**，★ **不是"哪一档在生效"**。
        #   ★★★ 为什么：★ `health` 是**无请求参数**的端点，★ 而档位**每轮由请求带来**
        #     ⇒ ★ 它**报不了"当前这一轮"**（★ 硬报就是编）。
        #   ★★★★ 2026-10-12 修：★ 原文本引用的是 `body.protector`，★ 而我改双档时
        #     误写成裸 `protector` ⇒ ★ **NameError（health 里没有这个变量）**（★ 我实测撞到）。
        #     ★ 正解：★ 报**静态描述** ⇒ ★ "哪一档在生效"由界面按勾选框显示。
        #   ★★★★★ 2026-10-12 再修（★ 纯净版核出的第二处）：★ 这里原先**重写了一个
        #     `"light"` 字面量** ⇒ ★ 与 `TIER_MODE` 成了**两个会漂的落点**
        #     （★ 判据 6 就数这个，★ 它当场数出 2 处）⇒ ★ 改为**引用** `TIER_MODE`。
        #     ★ 语义一字不变，★ 而真值回到**一处**。
        "tier": TIER_MODE,
        "tiers_available": ["work", "protector"],
        # ★★★★★ 2026-10-12：★ **两个指纹分开报**（★ 出处：持有方追问「相位指纹是什么」）
        #   · `phase_fp` —— ★ **相位规则**（可停/可看/可再选）的指纹 ⇒ ★ 所有节点共有
        #   · `scene_fp` —— ★ **层位表**（本产品的工作流程）的指纹 ⇒ ★ 换场景才变
        #   ★★ 为什么要两个：★ **同相 ≠ 同产品** —— ★ 分开才能分清"不同相"与"同相但不同产品"。
        "phase_fp": PHASE_FP,
        "scene_fp": SCENE_FP,
        # ★★★★★ C 组接线（2026-10-13）：★ **反-恒真对照**的样本数（★ 只读账 · ★ 见生成脚本 ⑤a-6）
        #   ★★ 它回答的是：★ **"这套机制有没有在动"** —— ★★ **不是"它有没有用"**
        #     （★ 后者要真人前后对读 · ★ 不是机器能判的 ⇒ ★ 字段名里就写清）。
        #   ★★★ 写法：★ `globals().get(...)` —— ★ **不是多此一举**：
        #     ★ 我在定位这个问题时，★ "直接调一个可能不存在的名字"会让整个 dict **先炸**、
        #       ★ 连诊断字段都出不来（★ 我实测撞到）⇒ ★ **这一处用 `globals().get` 是有意的**，
        #       ★ 它保证**即使装载失败，端点也回得来**（★ 且如实报 `不可核`，不静默判绿）。
        "对照_代理": (globals()["_账对照"]() if "_账对照" in globals()
                     else {"不可核": "★ `_账对照` 未装载 —— ★ 见生成脚本 ⑤a-6（它必须排在 `__main__` 之前）"}),
    })
    return out


# ---------------------------------------------------------------- API Key 设置（丙 · 2026-10-28）
#
# ★ 为什么加它：开源版**不能带真 key**（★ 那是纯净版的底线）⇒ 故第一次打开时，
#   必须有一条**能填 key 的路**。★ 而原版的铁律是「API Key 只从环境变量读」——
#   那条铁律的理由是**可核的**（见本文件文首 §隐私修 ①）：
#     「允许它由 HTTP 请求填 ⇒ **任意网页都能把它换掉**」
#   ⇒ ★★★ 故本实现**不拆那条理由，而是补上它缺的那一半**：
#     **POST 必须带本机令牌**（`x-rootthink-token`，启动时随机生成、只注入本服务打开的页面）。
#     没有它 ⇒ 403。**这就把"任意网页能换"挡在外面**，而界面仍在同一台机器上能填。
#
# ★★ 而**环境变量仍然优先**：若 key 来自 `DEEPSEEK_API_KEY`，写文件盖不过它
#   ⇒ ★ **如实回报"改不了"**，不假装保存成功（同原版 §隐私修 ② 的纪律）。

class KeyIn(BaseModel):
    api_key: str = ""


def _local_token_ok(request: Request) -> bool:
    """★ 本机令牌闸：证明请求来自**本服务打开的页面**，而不是别的网页。"""
    return request.headers.get(TOKEN_HEADER) == LOCAL_TOKEN


@app.get("/api/key")
def get_key():
    """★ 只回「配没配 + 掩码」，**绝不回传 key 本体**。

    ★★ 2026-10-28（依 D 第 17 轮 P2 修）：此前这条注释写「本端点不要求令牌」——
      **而它是假的**：中间件对所有 `/api/*` 都要求 `x-rootthink-token`（代码做对了，注释撒谎）。
      ★ 而那种注释会诱导下一个人**把闸修掉**，故改掉。
    """
    k = get_api_key()
    mask = ""
    if k:
        mask = (k[:5] + "…" + k[-4:]) if len(k) > 12 else "已配置"
    return {
        "key": bool(k),
        "mask": mask,
        "source": "env:" + KEY_ENV if (os.environ.get(KEY_ENV) or "").strip() else (
            "config.local.json" if CONFIG_FILE.exists() else (
                ".env.local" if (APP_DIR.parent / ".env.local").exists() else "none")),
        # ★ 来自环境变量时界面改不了 —— 前端据此禁用输入框并说明
        "settable_via_http": not (os.environ.get(KEY_ENV) or "").strip(),
    }


@app.post("/api/key")
def set_key(body: KeyIn, request: Request):
    """★ 写/清 `config.local.json`（★ 包根，与 `load_config()` 同一份）。

    · **必须带本机令牌**（`x-rootthink-token`）—— 否则 403。
    · 传非空 ⇒ 保存；传空 ⇒ 清除（只摘 api_key，别的键不动）。
    · ★ 若 key 来自环境变量 ⇒ **如实回报改不了**（不假装保存成功）。
    """
    if not _local_token_ok(request):
        raise HTTPException(403, (
            "★ 拒绝：本端点需要本机令牌 `" + TOKEN_HEADER + "`。"
            "它不是认证用户，是**证明请求来自本服务打开的页面** —— "
            "★ 没有它，任意网页都能把你的 key 换掉。"
        ))
    if (os.environ.get(KEY_ENV) or "").strip():
        return {"ok": False,
                "why": "当前 key 来自系统环境变量 {0}，界面改不了它 —— 请在系统环境变量里改。"
                       .format(KEY_ENV)}
    k = (body.api_key or "").strip()
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}
        if not isinstance(cfg, dict):
            cfg = {}
    except Exception:                                                    # noqa: BLE001
        cfg = {}
    if k:
        cfg["api_key"] = k
    else:
        cfg.pop("api_key", None)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    # ★ 写完之后**立刻回读**—— ★ 不报"我以为存了"，报"读得回来才叫存了"
    return {"ok": True, "key": bool(get_api_key())}


#: ★★★ 2026-10-28（A · 依敌手 D 第 17 轮 P0-1）：`base_url` 白名单**提到模块级**。
#:
#:   ★ 病灶（D 实测）：白名单只在 `POST /api/config` 里查（HTTP 一条路），
#:     而 `load_config()` 从 `config.local.json` 读 `base_url` 时**不做任何检查**。
#:     ⇒ 手改那个 JSON 文件，服务就把 Bearer key 送到攻击者指定的主机（三道 HTTP 闸全无效，
#:       因为**攻击根本不走 HTTP**）。
#:   ★★ 而 README 那句「没人能借这个服务把你的 Key 发去别处」因此是**假话**。
#:   ★★★ 修法（D 的原话）：「对 `base_url` 加与 `set_config` 同一白名单（**同一函数、不是两处**）」。
#:     故这里提炼成 `_base_allowed()`，两个调用点都用它。
_ALLOWED_BASE = ("https://api.deepseek.com",)


def _base_allowed(url: str) -> bool:
    """★ base_url 的唯一判据（`set_config` 与 `load_config` 共用本函数）。"""
    return (url or "").strip().rstrip("/") in _ALLOWED_BASE


@app.get("/api/config")
def get_config():
    """★ 不再回 key 的任何片段（此前回 `key_hint`＝后 4 位）。"""
    return {
        "base_url": CONFIG.get("base_url"),
        "model": CONFIG.get("model"),
        "temperature": CONFIG.get("temperature"),
        "max_tokens": CONFIG.get("max_tokens"),
        "has_key": bool(get_api_key()),
        "key_source": "env:" + KEY_ENV,
        "key_settable_via_http": not (os.environ.get(KEY_ENV) or "").strip(),  # ★ 丙：带令牌可设；环境变量优先时不可设
        "config_file_tainted": CONFIG_FILE_TAINTED,
        # ★ 前端版本自愈：页面用它跟自己 meta 里的版本比对，旧了就自动刷新
        "fe_version": str(int(INDEX_FILE.stat().st_mtime)),
    }


@app.post("/api/config")
def set_config(body: ConfigIn):
    # ★★ 通过项不得由 HTTP 填 —— 收到就拒，并给出改法
    if body.api_key is not None and body.api_key.strip() != "":
        # ★ 2026-10-28（丙）：`/api/config` **仍然拒收 key** —— 因为它是**无令牌闸**的端点。
        #   ★ 要设 key 请走 `POST /api/key`（那里有本机令牌闸）。
        raise HTTPException(400, (
            "本端点（/api/config）不接受 API Key —— 它没有令牌闸，任意网页都能打到。"
            "★ 要设置 key 请用 **POST /api/key**（需本机令牌 `" + TOKEN_HEADER + "`，"
            "从本服务打开的页面里自动带上）；或把 `{0}` 设进环境变量再重启。"
        ).format(KEY_ENV))
    # ★★★ 2026-10-13 安全修（★ 攻击演练 E·P0）：★ base_url 锁白名单 + model 限字符集。
    #   ★ 不设防的两个兑现（E 实测）：恶意上游收走 Bearer key（且落盘重启仍带毒）；借本机读内网。
    #   ★ 兼容网关 = 显式改这个元组（★ 不做运行时开关 —— ★ 改动面越小越防）。
    _ALLOWED_BASE = ("https://api.deepseek.com",)
    if body.base_url:
        _bu = body.base_url.strip().rstrip("/")
        if _bu not in _ALLOWED_BASE:
            raise HTTPException(400, "base_url 不在允许清单内（★ 防 key 外送与内网探测）。"
                                     "允许的值：https://api.deepseek.com")
        CONFIG["base_url"] = _bu
    if body.model:
        _m = body.model.strip()
        if not re.fullmatch(r"[A-Za-z0-9._\-]{1,64}", _m):
            raise HTTPException(400, "model 含不允许的字符（限字母 / 数字 / . _ -，≤64 位）")
        CONFIG["model"] = _m
    if body.temperature is not None:
        CONFIG["temperature"] = max(0.0, min(2.0, body.temperature))
    if body.max_tokens is not None:
        CONFIG["max_tokens"] = max(256, min(32768, body.max_tokens))
    save_config(CONFIG)          # ★ 已过滤掉 key 类字段
    return {"ok": True}


# ------------------------------------------------------------------ 账的形状（M1+M2）
#: ★ 「路」那一层的标记词（★ 与 `_LAYER_MARKS` 里的「路」同源 —— 不另立一套）。
_GATE_ROAD_WORDS = ("几条路", "这条路的代价", "一条路是", "路：", "代价是", "可以停",
                    "路有", "路是", "条路", "出路", "还有什么路", "几条出路")

#: ★★★ 2026-10-28（A 自查 · 实测撞到）：**词表会假阴**。
#:   实测：'…路有三条：B。' 一个词都没命中 —— 因为表里有「几条路」而那句写的是
#:   「路有三条」（★ 词序相反）⇒ 判成「缺路」⇒ **闸会给用户补一句「我没拆到路」，
#:   而那句话是错的**。
#:   ★★ 思考台说的是**假阳**（多算），而假阴**更坏** —— 因为**它会冤枉一整轮**。
#:   ★★★ 故加一道正则并联：**宁可多算（多一次假的有），不要漏算（冤枉一整轮）**。
_GATE_ROAD_RE = __import__("re").compile(r"[路]\s*(有|是|：|:)|\d\s*条路|条\s*(路|道)")

#: ★ 三层的标记词（★ 协议正本第 36-40 行 · **问 / 面 / 路**）。
#:   ★★ 为什么用标记词而不是解析结构：**这个产品的输出是自然语言**，
#:   而"哪一段属于哪一层"**没有机器可读的分隔符**。故这里**只数标记词出现没出现**，
#:   而**不判"那一层写得对不对"** —— ★ 后者是人的事（见 §13.2.5 的精神）。
_LAYER_MARKS = (
    ("问", ("卡在哪一句", "你卡在", "卡住你的那句", "真正卡")),
    ("面", ("有几面", "这一面", "哪一面", "面：", "几个面")),
    # ★★★ 2026-10-28（A 自查）：此前这里**另写了一份「路」的词表** —— 而它与
    #   _GATE_ROAD_WORDS 是**两处真值**。★ 那份《向外走》逐字：「同一条规则只在一区
    #   写一次。★ **两处写法必漂**。」
    #   ★★ 实测它漂了：闸那边加了「路有」而这边没加 ⇒ 同一段文本，
    #     _hit_road 判 True 而 _count_layers 数 0（⇒ H2 回显 2/3，冤枉一整轮）。
    #   ★★★ 故这里**改为引用** —— 让「路」的标记词**只有一处**。
    ("路", _GATE_ROAD_WORDS),
)


#: ★★★ H1 闸的阈值（2026-10-28 · 依思考台第 ④ 条）。
#:
#:   ★ 为什么是 900：按这个产品的三层结构，「路」通常在最后 1/3；
#:     而 900 字大约是「问 + 面」写完的长度。超过 900 仍无「路」⇒ 判它**注定不会出现**，
#:     开闸并**如实说"这一轮我没拆到路"**（★ 而不是让用户以为它还在写）。
#:   ★★ 而这个数是**可调的**，它不承诺任何精度 —— 它只决定"等多久"。
_GATE_MAX_CHARS = 900



def _hit_road(text: str) -> bool:
    """★ 「路」这一层**出现过没有**（★ 不是"写好没有" —— 后者判不了，见思考台问 2）。

    ★★ **两路并联：词表 + 正则** —— 而理由是**实测过的**：
      词表漏了「路有三条」这种词序（表里是「几条路」）⇒ 判成"缺路" ⇒
      ★★★ **闸会给用户补一句「我没拆到路」，而那句话是错的**（冤枉一整轮）。
      ★ 故这里**宁可多算**（多一次假的"有"），**不要漏算**（冤枉一整轮）——
      因为两种错的代价不对称：**多算只是放过一轮，漏算会诬告一轮。**
    """
    return any(w in text for w in _GATE_ROAD_WORDS) or bool(_GATE_ROAD_RE.search(text))


#: ★★★ L1 的判据（2026-10-28 · 依那份《自动拦你》的第一个建议）。
#:
#:   ★ 它原话：「拦不需要知道『该做什么』，只需要知道『什么不行』。」
#:   ★★ 而它也警告过：「**它会误伤** —— ……所以它的触发条件必须窄：
#:      『含判断性结论』这个前提要能判定，否则它天天卡人，卡几次就被人绕过。」
#:   ★★★ 故下面三条**都窄**，而且是**并列**（任一成立才算太模糊）——
#:      ★ 而**只要有一条不成立就放行**（★ 宁可放过，不要卡人）。
_MIN_MEANINGFUL_CHARS = 12
_VAGUE_ONLY = (
    "我很烦", "不知道", "没意思", "不知道怎么办", "迷茫", "难受", "emo",
    "烦", "累", "焦虑", "想不明白", "纠结",
)
_ABSTRACT_ONLY = ("人生", "意义", "方向", "未来", "自我", "价值", "活着", "到底要什么")


def _is_too_vague(text: str) -> tuple[bool, str]:
    """★ 输入是否**不足以定位"卡在哪一句"**（★ 而**不是**判它"没价值"）。

    ★★★ 三条判据（并列 · 任一成立）：
      ① 只有情绪词，没有任何具体人事时
      ② 太短（< 12 字）**且**无可指认的"人 / 事 / 时"
      ③ 全是抽象词，而没有一个具体场景

    ★★ 而返回的第二项是**为什么** —— ★ 因为那句问回话要**指名道姓**，
      不许含糊成"请你说清楚一点"（★ 那等于让用户自己猜哪里不清楚）。
    """
    s = (text or "").strip()
    if not s:
        return False, ""          # ★ 空输入交给上游的既有逻辑（不在这里重复管）

    # ③ 全是抽象词，而没有具体场景
    有抽象 = any(w in s for w in _ABSTRACT_ONLY)
    # ★★ 2026-10-28（A 自查 · 实测撞到）：「我」原本在这个表里 ⇒ 单独一个字「我」
    #   被判成"有人可指"而放过去了 —— 而**一个纯代词不构成"有事"**。
    #   ★ 故这里**去掉纯代词**（我 / 他 / 她 / 他们），只留有信息量的角色与场景词。
    有具体 = any(w in s for w in ("老板", "同事", "客户", "领导", "合伙人", "家人", "朋友",
                                  "昨天", "今天", "明天", "上周", "下周", "刚才", "这周",
                                  "说", "问", "要", "做", "签", "接", "拒", "走", "辞",
                                  "钱", "时间", "工作", "合同", "活", "单", "事", "这个", "那个"))
    if 有抽象 and not 有具体:
        return True, "这句里全是抽象词（{}……），没有一个具体场景".format(
            "、".join([w for w in _ABSTRACT_ONLY if w in s][:3]))

    # ① 只有情绪词
    去标点 = s.strip("。！？…，、,.!? ")
    if 去标点 in _VAGUE_ONLY:
        return True, "这句里只有情绪（「{}」），没有说清是什么事".format(去标点)

    # ② 太短 且 无可指认的人事时
    if len(去标点) < _MIN_MEANINGFUL_CHARS and not 有具体:
        return True, "这句只有 {} 个字，而没有人 / 事 / 时间可指".format(len(去标点))

    return False, ""


def _vague_reply(text: str, why: str) -> str:
    """★★ 那句**问回话** —— ★★★ 而它的硬要求是：**给两条路，其中 (b) 是兜底。**

    ★ 为什么必须有 (b)（这是 L1 全部风险的所在）：
      没有 (b) ⇒ 它就变成「你要先想清楚才能用」—— ★★ **而那与整个产品的立场相反**。
      ★ 而这个产品对一个"说不清"的人说的第一句话，**不该是"你不够清楚"**。
    """
    return (
        "★ 这句我拆不出东西 —— **而可能是我没听懂，不是你没说清。**\n\n"
        "为什么：{why}。\n\n"
        "★ 而你不用重写它。两条路，你挑一条：\n"
        "\n"
        "(a) **补一句具体场景**（谁、什么时候、发生了什么）—— 我再拆一次；\n"
        "\n"
        "(b) **就这样** —— 我**不拆三层**，只帮你**把这句本身摆正**：\n"
        "    看看这句话里有没有你自己都没注意到的两个东西（一个动作，一个对象）。\n"
        "\n"
        "★ 选 (b) 不是退而求其次 —— **它本来就是这把刀能做的一件事。**"
    ).format(why=why)


def _count_layers(text: str) -> dict:
    """★ **服务端数**：上一轮那三段各出现过没有（★ 与 `_build_account` 同一套标记词）。

    ★ 为什么必须由服务端数（那份报告逐字）：
      「**一个跨轮的量，且这个量由服务端算、不由我说**」——
      ★★ 因为「自我报告的量」与「自我报告的对错」是同一类不可靠。
    ★★★ 而它**只数出现没出现**，不判写得好不好（那是语义，判不了 —— 见思考台问 2）。
    """
    out = {}
    for 名, 词 in _LAYER_MARKS:
        次 = sum(text.count(w) for w in 词)
        out[名] = 次
    return out


def _layers_echo(prev_assistant: str) -> str:
    """★ 回显给模型的**一行读数**（★ 由服务端算，★ 不是让模型自报）。

    ★★ 为什么回显这件事本身有意义（那份报告逐字）：
      「它把『自我报告』变成『外部读数』。」
    """
    if not prev_assistant:
        return ""
    数 = _count_layers(prev_assistant)
    有 = [k for k, v in 数.items() if v]
    缺 = [k for k, v in 数.items() if not v]
    return (
        "\n\n## ★ 上一轮的三层读数（★ **由服务端数**，不是你自己报的）\n\n"
        "- 总数：**{0}/3 层出现过**\n"
        "- 出现过：{1}\n"
        "- **没出现：{2}**\n"
        "★ 这个数**只数「出现过没有」**，不判「写得好不好」——"
        "后者是语义，机器判不了（★ 不许假装判准）。\n"
        "★★ 而**缺的那一层，这一轮要么补上，要么如实说「这一层我给不了」** ——"
        "★ 不许用一句泛泛的话把它填上。\n"
    ).format(len(有), "、".join(有) or "（无）", "、".join(缺) or "（无）")


def _gate_missing_note() -> str:
    """★ 开闸时若因"注定没有路" ⇒ 如实补一句。★ 那是**记账**，不是判断。"""
    return ("\n\n★ 这一轮我**没拆到「路」**（这一层没出现，不是你漏看了）。"
            "你要 (a) 把话再往下说一句，还是 (b) 就先到这里？")


def _build_account(user_text: str, answer_text: str, session_id: str | None) -> dict:
    """★ 一次拆解的「账的形状」—— 只放**能核的**，不放进任何结论。

    ★★ 三条读法（★ 都来自协议自己的口径）：
      ① 数出来的   —— 原话字数 · 三层各出现几处 · 时间
      ② 按口径算的 —— 相位指纹 · 版本
      ③ 只能人答的 —— ★ "哪几层是模型硬补的" **机器不知道** ⇒ 写 `不可核`

    ★★★ 而它**不许**出现「建议」「你应该」「我建议」这类词 ——
      因为那会让这个工具成为判定主体（《向外走》§12.3）。
    """
    import time as _t

    答案 = answer_text or ""
    层 = {}
    for 名, 词 in _LAYER_MARKS:
        次 = sum(答案.count(w) for w in 词)
        层[名] = {"出现次数": 次, "判": "有" if 次 else "★ 没出现"}

    空层 = [k for k, v in 层.items() if v["出现次数"] == 0]

    return {
        # ── ① 从你的话里数出来的（★ 可核）──────────────────────────
        "①_数出来的": {
            "原话": user_text,
            "原话字数": len(user_text),
            "层": 层,
            "空着的层": 空层,
            "给出层数": 3 - len(空层),
            "总层数": 3,
        },
        # ── ② 按口径算的（★ 可复算）────────────────────────────────
        "②_按口径算的": {
            "相位指纹": PHASE_FP,
            "服务版本": VERSION if "VERSION" in globals() else "?",
            "时间": _t.strftime("%Y-%m-%dT%H:%M:%S"),
            "会话": session_id or "",
        },
        # ── ③ 只能人答的（★ 机器不知道 ⇒ 如实写不可核）──────────────
        "③_只能人答的": {
            "哪几层是模型硬补的": "不可核 —— ★ 机器分不出「他真给了」与「模型替他填了」",
            "哪几层你其实还没想清": "不可核 —— ★ 那是你的事，不是本工具能判的",
            "这份拆解对你有没有用": "不可核 —— ★ 本工具不评价自己的产出",
        },
        # ── 而这份账自己的边界（★ 不许省）──────────────────────────
        "这份账的边界": (
            "★ 它只记录「出现过什么」，不记录「写得对不对」。"
            "★ 而「空着的层」是**数出来的**（标记词 0 次），不是判出来的。"
        ),
    }


@app.post("/api/test")
def test_conn():
    """用一次最小对话验证 key / base_url / model。"""
    key = get_api_key()
    if not key:
        raise HTTPException(400, NO_KEY_MSG)
    url = CONFIG["base_url"].rstrip("/") + "/chat/completions"
    try:
        _egress_log(url, "test_conn", 64)
        r = httpx.post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": CONFIG["model"], "messages": [{"role": "user", "content": "hi"}],
                  "max_tokens": 4},
            timeout=20, trust_env=False,
        )
    except Exception as e:
        # ★★★ 2026-10-13 安全修（★ 攻击演练 E·P0）：★ 错误详情只进本机控制台，不回显 ⇒ 防端口探测。
        print("[test_conn] ★ 上游连接失败：{}".format(e), flush=True)
        raise HTTPException(502, "上游连不上（★ 详情看本服务控制台，不回显给调用方）")
    if r.status_code != 200:
        # ★★★ 同上：★ 上游响应体可能反射内网/别服务的内容 ⇒ ★ 只回状态码（★ 防内网读原语）。
        raise HTTPException(r.status_code, "上游返回 {0}（★ 不回显响应体）".format(r.status_code))
    data = r.json()
    return {"ok": True, "reply": data.get("choices", [{}])[0].get("message", {}).get("content", "")}


@app.get("/api/sessions")
def list_sessions():
    db = _load_sessions()
    out = []
    for s in sorted(db["sessions"], key=lambda x: x["updated"], reverse=True):
        # ★ 会话列表不需要档位 ⇒ 不回 mode（★ 档位是**每轮**的属性，★ 由回放时 `turns[i].protector` 带出）
        out.append({"id": s["id"], "title": s["title"], "updated": s["updated"],
                    "turns": len(s["turns"])})
    return out


@app.post("/api/sessions")
def create_session(body: SessionIn | None = None):
    db = _load_sessions()
    s = {
        "id": uuid.uuid4().hex[:12],
        "title": (body.title.strip()[:200] if body and body.title and body.title.strip() else "新对话"),
        # ★ 2026-10-13 安全修（★ 攻击演练 E·P2-1）：★ 标题截 200 —— 5 MB 标题曾把账撑到 15.7 MB。
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "updated": time.time(),
        "turns": [],
    }
    db["sessions"].append(s)
    _save_sessions(db)
    return s


@app.get("/api/sessions/{sid}")
def get_session(sid: str):
    s = _find_session(_load_sessions(), sid)
    if not s:
        raise HTTPException(404, "会话不存在")
    return s


@app.patch("/api/sessions/{sid}")
def rename_session(sid: str, body: SessionIn):
    db = _load_sessions()
    s = _find_session(db, sid)
    if not s:
        raise HTTPException(404, "会话不存在")
    if body.title and body.title.strip():
        s["title"] = body.title.strip()[:40]
        _save_sessions(db)
    return {"ok": True}


@app.delete("/api/sessions/{sid}")
def delete_session(sid: str):
    db = _load_sessions()
    before = len(db["sessions"])
    db["sessions"] = [s for s in db["sessions"] if s["id"] != sid]
    if len(db["sessions"]) == before:
        raise HTTPException(404, "会话不存在")
    _save_sessions(db)
    return {"ok": True}



@app.get("/api/sessions/{sid}/export")
def export_session(sid: str):
    """把一个会话（行使史）导出为 Markdown 文档下载。"""
    s = _find_session(_load_sessions(), sid)
    if not s:
        raise HTTPException(404, "会话不存在")
    safe_title = "".join(c for c in s["title"] if c not in '\\/:*?"<>|').strip() or "对话"
    # ★ 2026-10-09 修：清洗后若不含任何「字母/数字/中文」（如标题是纯符号），换可读兜底名（防 "---.md" 类不可读下载名）
    if not re.search(r"[a-z0-9\u4e00-\u9fff]", safe_title, re.IGNORECASE):
        safe_title = "对话导出 " + time.strftime("%Y-%m-%d %H%M")
    lines = [
        f"# {s['title']}",
        "",
        f"> 导出自 拆解器（外发 · 最精简版）· {time.strftime('%Y-%m-%d %H:%M')} · "
        f"共 {len(s['turns'])} 条记录（本机留存 · 原文未改）",
        "",
    ]
    for t in s["turns"]:
        if t.get("role") == "user":
            tag = "🧑 我" + (f"（{t.get('mode','')}{' · 护根' if t.get('protector') else ''}）" if t.get("mode") else "")
        else:
            # ★ 2026-10-09：助手侧也带上「护根」标记（与界面 index.html:680 同口径）。
            #   旧数据无该字段 ⇒ 自然退化为默认「🪞 拆解器」，无破坏。
            #   ★ 2026-10-13：★ 界面自称统一为产品名「拆解器」（★ 原为作者侧旧名）。
            tag = "🪞 拆解器" + (" · 护根" if t.get("protector") else "")
        lines += [f"## {tag} · {t.get('ts','')}", "", t.get("content", ""), ""]
    md = "\n".join(lines)
    fname = quote(f"{safe_title}.md")
    return Response(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fname}"},
    )


@app.post("/api/chat")
def chat(body: ChatIn):
    """流式对话：SSE。事件：{"delta": "..."} 增量 / {"error": "..."} / {"done": true}"""
    # ★★★ 2026-10-13 安全修（★ 攻击演练 E·P2-1/P2-3）：★ 单条消息上限 64 KB ——
    #   ★ 防把会话账与界面拖垮，★ 也让 `_乱()` 的 O(n²) 在**任何输入**下都有界（E·P2-3 随之消解）。
    if len(body.message) > 65536:
        raise HTTPException(413, "单条消息上限 64 KB")
    s = _find_session(_load_sessions(), body.session_id)
    if not s:
        raise HTTPException(404, "会话不存在")
    # ★★★★★ L1（2026-10-28 · A 自查 · 第二次挪位）：「输入太模糊」这一条**必须在 key 检查之前**。
    #   ★ 病灶（实测撞到两次）：
    #     ① 第一版它在 gen() 里判 —— 而 gen() 在 key 检查**之后**才被调用
    #        ⇒ **没有 key 时它永远到不了**。
    #     ② 第二版我用 key = get_api_key() 做锚 —— ★ 而那个锚在 /api/test 里**也有一份**，
    #        于是一整块被插进了 	est_conn()（★ 那个函数**没有 ody**）⇒ 死代码。
    #   ★★ 而它**该在这里**，理由是语义的：兜底 (b)「就这样，我帮你把这句本身摆正」
    #      **本来就不需要模型** ⇒ 它不该被 key 那道门挡住。
    #   ★★★ 故：**紧贴 if not s: 之后、key = get_api_key() 之前**。
    _too_vague, _vague_why = _is_too_vague(body.message)
    if _too_vague:
        _vr = _vague_reply(body.message, _vague_why)

        def _vg():
            yield f'data: {json.dumps({"delta": _vr}, ensure_ascii=False)}\n\n'
            yield f'data: {json.dumps({"done": True, "to_vague": True}, ensure_ascii=False)}\n\n'

        # ★ 而它**不落账**：那一轮没有产生拆解，把一句「我没听懂」记成一轮对话会把账弄脏。
        return StreamingResponse(_vg(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


    key = get_api_key()
    if not key:
        raise HTTPException(400, NO_KEY_MSG)
    # ★★★ fail-closed（★ 本外发版加）：★ 场景层位表是**唯一的产品定义** ⇒
    #   ★ 读不到它 ⇒ **拒服务并说清原因** —— ★ 不许静默降级成"看起来能用"。
    if not SCENE_PROTOCOL:
        raise HTTPException(500, "★ 协议正本缺失或读不到（app\\protocol\\拆解器·协议.md）—— "
                                 "★ 本工具不许在没有层位表的情况下作答。")

    # ★★★ 唯一档位就落在这里
    #   ★★ `return_breakdown=True` ⇒ ★ **一次构建**同时拿到「提示词」与它的「分段读数」
    #     —— ★★ 两者**同源** ⇒ ★ 不可能出现"量的是另一个提示词"（★ 原版那个病）。
    #   ★★★ `_doc_context(body.doc_ids)` **已去**（★ 文档上传库整块已去）。
    #   ★★★★ 而**档位由请求带来**：★ `TIER_MODE` 锁在 `"light"`（★ `ChatIn` 默认值 = 唯一真值）；
    #     ★ `body.protector` 默认 `False` = 工作模式 —— ★ 用户**显式**开才是护根。
    #   ★★★★★ A 组接线（2026-10-13）：★ **本轮的"乱"读数在这里算好、传进去**
    #     （★ 因为**只有这里手上有用户原文** —— ★ 账里只存指纹，★ 原文不落盘）。
    _乱读, _乱纪 = _乱纪律(body.message)
    # ══════════════════════════════════════════════════════════════════════
    # ★★★ L1 的**位置**（2026-10-28 · A 自查 · 已上移到 key 检查之前）
    #
    #   ★ 病灶（实测撞到）：`_is_too_vague` 原本在这里判（★ 而这里在 key 检查**之后**）
    #     ⇒ **没有 key 时，流在第 1378 行就被拒了 ⇒ L1 永远到不了。**
    #   ★★ 而那不是"位置没选好"，是**语义错了**：
    #     L1 的兜底 (b)「就这样，我帮你把这句本身摆正」**本来就不需要模型**。
    #   ★★★ 故它已经移到 `key = get_api_key()` 之前（见上面那段 `_too_vague` 的分支）。
    #     ★ 这里只留这一行注释，**不再重复判**（两处判必漂）。
    # ══════════════════════════════════════════════════════════════════════

    system, _sys_bd = build_system_prompt(body.session_id, bool(body.protector),
                                         乱纪律=_乱纪, return_breakdown=True)
    # ══════════════════════════════════════════════════════════════════════
    # ★★★ H2（2026-10-28 · 依那份报告的「建议三」）：
    #   把「上一轮给了几层」变成**一个跨轮的量**，而它**由服务端算、不由模型报**。
    #   ★ 为什么（逐字）：「『机制』要的是：一个跨轮的量，且这个量由服务端算、不由我说。」
    #   ★★ 而它把「自我报告」变成「外部读数」—— 那两件事的不可靠是同一类。
    #   ★★★ 而它**只数「出现过没有」** —— 不判「写得好不好」（见思考台问 2 的切分）。
    # ══════════════════════════════════════════════════════════════════════
    _prev_assistant = ""
    for _t in reversed(s["turns"]):
        if _t.get("role") == "assistant":
            _prev_assistant = _strip_think(_t.get("content", "") or "")
            break
    _echo = _layers_echo(_prev_assistant)
    if _echo:
        system = system + _echo

    # ★★ 本外发版**去掉了 `host_gate`**（★ 原件是 `core\host_gate.py`）——
    #   ★ 它管的是"护根**被谁改掉**之后不许假装还在"；★ 而本版的护根**只有一处真值**
    #     （★ `ChatIn.protector`，★ 默认 `False`）⇒ ★★ 它在此**永远不触发**（= 死代码）。
    #   ★★★ 但**为什么不在**这件事写在这里：★ 若将来有人把那个默认值改成 `True`，
    #     ★ **本版没有这道闸**（★ 原版那道已去）⇒ ★ 唯一的防线是那一处默认值
    #     （★ 以及界面上那个勾选框 —— ★ 默认不勾）。
    # 历史轮里重档的 <think> 块不回灌（省 token；行使史原文保留）
    history = []
    for t in s["turns"][-HISTORY_TURNS_LIMIT * 2:]:
        c = t.get("content", "")
        if t.get("role") == "assistant":
            c = _strip_think(c)
        if t.get("role") == "user" and not c.strip():
            c = "（该轮用户只附带文档，未写文字。）"   # 纯文档轮：账上留空，回灌时补占位
        history.append({"role": t.get("role"), "content": c})
    # ★★★ 2026-10-09 本项目加（★ 记忆机制落点一的后半 · ★ **管住历史**）：
    #    ★★★ 为什么（★ 实测 · 见 `core/loop.py` 的 `bound_history` 头注）：
    #       ★ `HISTORY_TURNS_LIMIT = 24` **只数轮、不量字符** ⇒
    #       ★★ 实测：★ 第 7 轮（6 轮历史 × ~2,246 字符）= **26,952 字符 = 约束的 94%**；
    #       ★★★ 第 7 轮 + 一份 21,000 字符文档 ⇒ **约束 101,082 · 超预算 19%。**
    #    ★★ 而**管它有两条路，只有一条合规**：
    #       · ★ 静默砍 ⇒ ★★ **违反 `:449`** —— ★「**不许截断后假装读到了**」；
    #       · ★★★ **显形砍** ⇒ ★ 砍掉的**告诉模型**（★ "你不知道那部分说了什么 · 不许假装记得"）
    #         ★ **并且告诉人**（★ 下面那行 stderr）⇒ ★ 这才是"有损"而不是"降级"。
    #    ★ 取舍：★ **从最新往回取 · ★ 只整轮 · ★ 当前这一轮永不砍**（★ `bound_history` 里写死了）。
    _hist_note = ""
    try:
        import loop as _looph
        history, _hist_note = _looph.bound_history(
            history, turns_limit=HISTORY_TURNS_LIMIT)
        if _hist_note:
            system = system + _looph.history_note_section(_hist_note)
            print("[context] ★ 历史已按字符预算收窄；★ 已把这件事**显形**给模型与用户",
                  file=sys.stderr)
    except Exception as _e:                                               # noqa: BLE001
        # ★★★ 2026-10-28（依 D 第 17 轮 P1-3）：
        #   · 此前这里是 `_sys`，而 `_sys` 只在 `atomic_io` 导入**失败**的分支里定义
        #     ⇒ 主路径上 NameError；而 except 体里又用一次 ⇒ **二次 NameError ⇒ chat 500**。
        #   · ★ 更坏的是这段文案：「历史收窄不可用（★ 本轮下发全量）」——
        #     而此刻 `bound_history` **已经执行成功**（只不过打印失败了）。
        #     **已收窄却报告"未收窄"，消息与事实相反。**
        #   · 故：改用标准库 `sys`，并把文案改成**只说打印失败**（不替收窄下结论）。
        print("[context] ★ 历史收窄**已完成**，但它的提示行打印失败：{0}: {1}"
              "（★ 别把这条读成「没收窄」）".format(type(_e).__name__, _e),
              file=sys.stderr)
    # ★ 本外发版无"随轮附文档"⇒ 空输入退化为一个句号（★ 不落账、不显示）
    user_now = body.message.strip() or "。"
    msgs = [{"role": "system", "content": system}, *history,
            {"role": "user", "content": user_now}]

    # ★★★ 2026-10-09 本项目加（★ 记忆机制落点一的后半 · ★ **只量、只落账，★ 不改任何判定**）：
    #    ★ 出处：★《方案·顾问记忆机制》§5.2 —— 「**没有读数的预算，就是下一个"看起来正常"**」
    #    ★★ 三段此前**无处可量**：★ 系统提示（拆得出）· ★ **对话历史**（★ 只知轮数 24、★ 不知字符）·
    #       ★ **附带文档**（★ 只知有总量截断、★ 不知现值）。
    #    ★★★ 故此处把三者拼成**一行读数**，★ 超限**只报红、★ 不静默截断**（★ 与 `:449` 那条立场一致）。
    try:
        import loop as _loop2
        # ★★★ 本外发版：★ **不重建** —— ★ 直接用上面那次构建的**同一个对象**（`system` / `_sys_bd`）。
        #   ★ 真提示词与它的分段读数**必须同源**，★ 否则读数就是"另一个东西的长短"。
        #   ★ 另：★ 本版**没有"附带文档"**（★ 随文档库一起去掉）⇒ `doc_chars=0`。
        _rep = _loop2.context_report(
            system, _sys_bd,
            history_chars=sum(len(m.get("content", "")) for m in history),
            doc_chars=0)
        _probs = _loop2.context_report_check(_rep)
        print("[context] {0}".format(_rep["行"]), file=sys.stderr)
        for _x in _probs:
            print("[context] {0}".format(_x), file=sys.stderr)
    except Exception as _e:                                               # noqa: BLE001
        print("[context] ★ 读数不可用：{0}: {1}".format(type(_e).__name__, _e), file=sys.stderr)

    # ★★★ 本外发版：**没有工具**。
    #   ★ 原版的 `web_search` / `read_file` / `write_file` **三个工具的定义与派发已整块删除**
    #     （★ 出处：A《核对·最精简版与相干波束》§2.1 第 1 条 ——
    #       ★「★ **工具的提示词与派发必须同删**」★ 否则会出现更坏的一种：
    #       ★ **"模型说能读文件，而它不能"**）。
    #   ★★ 故这里恒为 `None` ⇒ 下发的请求里**不带 tools** ⇒ 模型只能正面作答，不能调工具。
    tools = None
    url = CONFIG["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": CONFIG["model"],
        "stream": True,
        "temperature": CONFIG.get("temperature", 1.0),
        "max_tokens": CONFIG.get("max_tokens", 4096),
    }
    # 用量统计：DeepSeek 支持 stream_options.include_usage（最后一个 chunk 带 usage）。
    # 只对 DeepSeek 域名开启——别家兼容网关可能不认这个参数，避免整条请求被拒。
    if "deepseek" in url.lower():
        payload["stream_options"] = {"include_usage": True}
    headers = {"Authorization": f"Bearer {key}"}

    def gen():
        acc = []
        # ★★★ H1 闸（2026-10-28 · 依思考台第 ④ 条）：**开闸之前不往外发**，只累积。
        #   ★ 为什么：`yield` 出去的字节**收不回** —— 故"先发后判"永远只能记账。
        #   ★★ 而整段缓冲会白屏 20-40 秒 ⇒ 故只等到「路」那一段出现就开闸。
        #   ★★★ 而「问」「面」写错仍判不了 —— 那道闸**承认自己只有这一档精度**（不假装）。
        _gate_open = False
        _gate_sent = 0

        # ★★★ B-36：定义提到这里 —— 因为**失败出口在它之前**（实测：call :1328 < def :1427）
        #   ★ 若不提，失败路径会 NameError ⇒ **失败轮永远不落账**，比不修还坏。
        # ★★★ B-36（v3.7 加）：**失败轮也要落账** —— 否则用户那句话随失败一起消失。
        #   实测病灶：`turns.append` 原在成功路径内，而**失败出口在它之前**（上游非 200 · 请求中断）
        #   ⇒ 那两条路径**直接 return**，于是 `sessions.json` 里**那一轮 user 与 assistant 都不存在**。
        #   ★ 实证：`sessions.json` 里 user 与 assistant **永远成对**（13/13 · 8/8 …）⇒ 失败时丢的是**两边**；7 个会话对不上账。
        #   ★ 口径：`ok=True` ⇒ 与原来逐字相同；`ok=False` ⇒ 仍落 **user 那条**，
        #     assistant 只落已收到的部分，并加 `incomplete: true` 与 `error: <短原因>`（不许静默）。
        def _persist_round(ok: bool, err: str = "") -> None:
            try:
                db = _load_sessions()
                s2 = _find_session(db, body.session_id)
                if s2 is None:
                    return
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                s2["turns"].append({"role": "user", "content": body.message, "ts": ts,
                                    "mode": TIER_MODE, "protector": body.protector})
                # ★ 2026-10-09（C 核验《护根模式一条验证记录》后加）：
                #   此前**只有 user 轮**落 mode/protector，助手轮不落 ⇒ 两处失真：
                #     ① 界面回放（index.html:477 取 t.protector）拿不到 ⇒ **刷新后「护根」标记丢失**；
                #     ② 导出（export_session）取同一字段 ⇒ 「行使史留痕」答不出"哪几轮开了护根"。
                #   ★ 账（history/session_log.jsonl）一直是对的 —— 补这一处是让**展示层追上账层**。
                msg = {"role": "assistant", "content": "".join(acc), "ts": ts,
                       "protector": bool(body.protector)}
                if ok:
                    msg["usage"] = {**usage, "elapsed_s": round(time.time() - t0, 1),
                                    "model": CONFIG["model"]}
                else:
                    msg["incomplete"] = True
                    msg["error"] = (err or "未知")[:200]
                s2["turns"].append(msg)
                s2["updated"] = time.time()
                if s2.get("title") in ("新对话", "") and body.message.strip():
                    s2["title"] = body.message.strip()[:20]
                _save_sessions(db)
            except Exception as _e:                                  # noqa: BLE001
                print(f"[B-36] 落档失败（**不影响本次回答**）：{_e}", flush=True)
        hist = list(msgs)
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        t0 = time.time()
        # ★★ C 案（2026-10-08）：「输出触顶」的**服务侧捕获点**。
        #   ★ 为何要有它：此前**全文件 0 处**处理 `finish_reason` ⇒ 上游因触顶停止时
        #     被当正常收尾转发 ⇒ 前端呈现为「话说半句自己停了」，**没有任何提示**。
        #     ★ 2026-10-08 实测：`max_tokens=4096` 时输出精确停在 4095（顶格 99.98%）。
        #   ★ 语义：`finish_reason == "length"` 是**上游权威判定**——
        #     ★ 服务**只读它、不猜**（与 not_output 同一纪律：不替上游重判）。
        #   ★ 实现：任一 tool 轮次出现 length ⇒ 记下（★ 覆盖多轮工具调用的每一轮）。
        _truncated = False
        _trunc_round = None
        try:
            tool_rounds = 0
            while True:
                use_tools = tools if tool_rounds < MAX_TOOL_ROUNDS else None
                round_calls = {}
                _egress_log(url, "chat/stream",
                            sum(len(m.get("content") or "") for m in hist))
                with httpx.stream("POST", url, headers=headers,
                                  json={**payload, "messages": hist,
                                        **({"tools": use_tools} if use_tools else {})},
                                  timeout=180, trust_env=False) as r:
                    if r.status_code != 200:
                        body_text = r.read().decode("utf-8", "replace")[:300]
                        _persist_round(False, "上游非200")
                        yield f'data: {json.dumps({"error": f"上游 {r.status_code}: {body_text}"}, ensure_ascii=False)}\n\n'
                        return
                    for line in r.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]":
                            break
                        try:
                            d = json.loads(chunk)
                        except Exception:
                            continue
                        if d.get("usage"):      # stream_options.include_usage：末尾 chunk 带 usage（choices 为空）
                            u = d["usage"]
                            for k in usage:
                                usage[k] += u.get(k, 0) or 0
                            continue
                        chs = d.get("choices") or [{}]
                        delta = chs[0].get("delta", {})
                        # ★ C 案：捕获上游的 finish_reason（★ 只在非空时看，流中绝大多数帧为 null）
                        _fr = chs[0].get("finish_reason")
                        if _fr == "length":
                            _truncated = True
                            _trunc_round = tool_rounds
                        if delta.get("content"):
                            acc.append(delta["content"])
                            # ══════════════════════════════════════════════════
                            # H1 闸（2026-10-28 · 依思考台第 ④ 条）
                            #
                            #   开闸条件（二者之一）：
                            #     ① 累积文本里**出现「路」的标记词** ⇒ 三层都着落了
                            #     ② 累积到 _GATE_MAX_CHARS 仍无「路」⇒ 判它**注定不会出现**
                            #
                            #   ★ 开闸之前：**一个字都不发**（★ 否则收不回）
                            #   ★★ 开闸那一刻：把**已累积的全部一次性发出**（★ 用户看到的是一整段，
                            #      而不是"它卡住了"）
                            #   ★★★ 而②那条开闸时**必须补一句"没拆到路"** —— 那是记账，不是判断
                            # ══════════════════════════════════════════════════
                            if _gate_open:
                                yield f'data: {json.dumps({"delta": delta["content"]}, ensure_ascii=False)}\n\n'
                            else:
                                _sofar = "".join(acc)
                                _why = None
                                if _hit_road(_sofar):
                                    _why = "hit"
                                elif len(_sofar) >= _GATE_MAX_CHARS:
                                    _why = "give_up"
                                if _why:
                                    _gate_open = True
                                    _payload = _sofar
                                    if _why == "give_up":
                                        _payload += _gate_missing_note()
                                        acc.append(_gate_missing_note())
                                    _gate_sent = len(_payload)
                                    yield f'data: {json.dumps({"delta": _payload}, ensure_ascii=False)}\n\n'
                # ★★★ 本外发版：**没有工具** ⇒ 一轮即收束。
                #   ★ 原版此处是「汇聚 tool_calls → 不空则进工具轮 → 派发」的整块逻辑；
                #     ★ 依 A《核对·最精简版与相干波束》§2.1 第 1 条：★ **工具的提示词与派发必须同删**
                #     —— ★ 否则会出现更坏的一种：★ **"模型说能读文件，而它不能"**。
                #   ★★ 而它**结构上不可能发生**：★ `tools = None` ⇒ 请求里不带 tools ⇒ 无 tool_calls。
                break
        except Exception as e:
            _persist_round(False, "请求中断")
            yield f'data: {json.dumps({"error": f"请求中断：{e}"}, ensure_ascii=False)}\n\n'
            return

        # ★★★ H1（2026-10-28）：**流结束了而闸还没开** ⇒ 必须把累积的全发出去。
        #   ★ 为什么这条必须有：若模型的回答**从头到尾没有「路」**且**短于 _GATE_MAX_CHARS**
        #     （例如它只说了「问」和「面」就停了），那上面两个开闸条件**一条都不触发** ⇒
        #     ★★ **用户会看到一片空白** —— 那比"缺路"坏得多（★ 那是"什么都没有"）。
        #   ★ 故这里兜底：**把累积的全发，并如实补一句"没拆到路"**。
        if not _gate_open and acc:
            _tail = "".join(acc) + _gate_missing_note()
            acc.append(_gate_missing_note())
            _gate_open = True
            yield f'data: {json.dumps({"delta": _tail}, ensure_ascii=False)}\n\n'
            print("[gate] ★ 闸到流结束才开：这一轮没出现「路」（★ 已如实补一句）", file=sys.stderr)

# 落档（行使史）—— ★ B-36：成功与失败**同走一个函数**
        # 落档（行使史）
        db = _load_sessions()
        s2 = _find_session(db, body.session_id)
        usage_ev = {**usage, "elapsed_s": round(time.time() - t0, 1), "model": CONFIG["model"]}
        _persist_round(True)

        # 用量事件：本轮 token 消耗（多轮工具调用已累加）。无 usage 时前端不显示该段。
        yield f'data: {json.dumps({"usage": usage_ev}, ensure_ascii=False)}\n\n'


        #
        #   ①正文落款 = 展示（随对话走）· ★②会话侧 = **账**（唯一能被对账的地方，A3 的载体）
        #   · ③事件类 = **标注**，写进②的同一轮记录（**不单独开账**）
        #
        #   七项（§13.2 逐字）：材料指纹 · 位集 · 位来源 · 层 · 是否层判不明 · M4 反方条件 · 落款形态(1-5)
        #   ★ 硬规：**不落材料原文**（只 长度+首20字+sha256）· **形态 4/5 也进账、位集写空**
        #   ★ 提不出的项 ⇒ 显式 `undeclared`（**不许静默留空**）
        # ★★ 记账返回的**那一条记录**要留住 —— ★ 后续「不算输出」的流末帧要用它的 `not_output`
        _rec = None
        # ★★★★★ A/C 组落账（★ 2026-10-13 加 · ★ 见生成脚本 ⑤a-6）
        #   ★★★ 为什么**在这里当场算**（★ 而不是在 `chat` 里算好、闭包传进来）：
        #     ★ 我原先在 `chat` 段算、★ 在这段（`gen` 里）用 —— ★ 而**它落账时始终是 `None`**。
        #     ★★ 根因不好查（★ 那段有 `try/except` ⇒ ★ 异常被吞、★ 只打一行"记账失败"）。
        #     ★★★ 而**正解本来就更简单**：★ `body.message` **在这个作用域里就有** ⇒
        #       ★ **当场算** ⇒ ★ 不跨作用域、★ 不靠闭包、★ 也**不另存状态**。
        #     ★★★★ 判据（★ 可复用）：★ **要用一个值时，就在用它的那个作用域里算它。**
        #       ★ 跨层传值只在"那里算不出来"时才值得（★ 而这里算得出来）。
        _乱读, _乱纪 = _乱纪律(body.message)
        try:
            import session_log as _sl
            _rec = _sl.record(body.session_id, body.message, "".join(acc),
                              mode=TIER_MODE, protector=bool(body.protector),
                              turn_no=(len(s2["turns"]) // 2) if s2 is not None else None,
                              形状=_形状("".join(acc)),
                              乱=_乱读, 乱纪律=_乱纪)
        except Exception as _e:                                  # noqa: BLE001
            # ★★★★ 2026-10-13 修：★ 原来只打 `{_e}` ⇒ ★ **异常类型与位置都丢了** ⇒
            #   ★ 我查 A/C 落账失效时**只看到"记账失败"、看不出失败在哪**（★ 实测代价）。
            import traceback as _tb
            _loc = _tb.extract_tb(_e.__traceback__)[-1]
            print(f"[session_log] 记账失败（**不影响本次回答**）："
                  f"{type(_e).__name__}: {_e} @ {_loc.filename}:{_loc.lineno}", flush=True)

        # ★★★ 「不算输出」的**服务侧落点**（v3.7 · 2026-10-08 · 依决定单「丙·分层」）
        #   ★ 为何在**流末**：★ 底判据要**先有落款**，而落款在回答末尾
        #     ⇒ ★★ **"该轮不算输出"在时序上不可能阻断那一轮** ⇒
        #     ★ 故它只能落成**事后如实回显** + **账里留痕**（★ 这一条已写在决定单里）。
        #   ★ 契约：★ 底 `judge_round()` 返回 `not_output` / `not_output_why`（★ 服务**只转发，不重判**）。
        #   ★ 取不到 ⇒ 字段不出现在帧里（★ 不编一个 False 冒充"算输出"）。
        _no = None
        try:
            if isinstance(_rec, dict):
                _no = _rec.get("not_output")
        except Exception:                                        # noqa: BLE001
            _no = None
        # ══════════════════════════════════════════════════════════════
        # M1+M2（2026-10-28 · 依 docs/优化方案·按档分）
        #
        # ★ M1「交出账的形状」：一次拆解的可复制件 —— 原话逐字 · 三层各拆出什么 ·
        #   哪几层空着 · 时间与版本。★ 而它**不含任何"建议"类结论** ——
        #   因为那个一旦有，这个工具就成了判定主体（《向外走》§12.3 三条禁令）。
        #
        # ★★ M2「三类标记」：凡能数的系统替你数；凡只能人答的系统不该替他答。
        #   ① 从你的话里数出来的（可核）
        #   ② 机器按口径算的（可复算）
        #   ③ 要你自己答的（★ 机器不知道 ⇒ 写「不可核」，不许编）
        #
        # ★★★ 层数是**三**（问 / 面 / 路），不是四 ——
        #   协议正本第 33-40 行逐字：「本场景三层」。
        #   而本方案第一版写成四层，是从根系统框架搬来的 —— 那句警告来自《向外走》：
        #   「交付档只能取子集 + 换措辞，**不许另立一套**」。
        # ══════════════════════════════════════════════════════════════
        # ★★★ 2026-10-28（A 自查 · 而它是 D 第 17 轮 P1-1 的同一个形状）：
        #   我第一版写的是 _acc_text —— ★ **那个变量不存在**，而变量叫 cc（一个 list）。
        #   而它被下面那句 except Exception 吞成「账没算成」⇒
        #   ★★ **一个自称账的东西，永远算不成、而零告警** —— 与 P1-1 一字不差。
        #   ★ 故两件事一起修：变量名改对；**except 里必须带上异常类型**，
        #     不许把我用错了变量名渲染成账没算成。
        try:
            _acct = _build_account(body.message.strip(), "".join(acc), session_id)
        except Exception as _ae:                                        # noqa: BLE001
            _acct = {"不可核": "账没算成：{0}: {1}".format(type(_ae).__name__, str(_ae)[:120]),
                     "★ 这不是数据缺失": "是本服务的账没算出来 —— 那是一处实现缺陷，不是你的输入有问题"}

        _done = {"done": True}
        if _acct is not None:
            _done["account"] = _acct
        # ★ C 案：把「触顶」如实回显（★ 只在**真触顶**时出字段 —— 不编一个 False 冒充正常）
        if _truncated:
            _done["truncated"] = True
            _done["truncated_why"] = (
                "输出触顶：上游以 finish_reason=length 停止（max_tokens={0}）".format(
                    CONFIG.get("max_tokens")))
            _done["truncated_max_tokens"] = CONFIG.get("max_tokens")
            if _trunc_round is not None:
                _done["truncated_round"] = _trunc_round
        if _no is not None:
            _done["not_output"] = bool(_no)
            if _no:
                _done["not_output_why"] = str((_rec or {}).get("not_output_why") or "")[:200]
        yield f'data: {json.dumps(_done, ensure_ascii=False)}\n\n'

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ══════════════════════════════════════════════════════════════════
# A 组 · 把「乱」变成可数（★ 2026-10-13 加 · ★ 出处：《优化建议》第 4 条）
#
#   ★ 为什么要它：★ 缺它 ⇒ **不知道什么时候该启动"停/看/再选"** ——
#     ★★ 而在此之前，注入与否**全看上一轮形状**（★ 那是"格式"信号，★ **不是"乱"信号**）。
#
#   ★★ 口径：★ **照搬现成表，不自造**（★ 建议原话）：
#     · 同一语义重复 ≥ 3  · 未解释指代 ≥ 2  · 时间压力词 ≥ 1  · 冲突诉求 ≥ 1
#
#   ★★★ 三条纪律（★ 都写进行为）：
#     ① **正则只做形状**：★ 去标点归一后数重复；★ **判不了语义** ——
#        故"同一语义"用「同句归一后重复」作**代理**，★ 并**如实标它是代理**（★ 不冒充实义）。
#     ② **阈值就是闸**：★ 任一项到阈 ⇒ 触发（★ 触发的是**注入一条纪律**，★ **不是阻断那一轮**）。
#     ③ ★★★ **它挡不住那一轮** —— ★ 依《优化建议》§四 第 2 条：
#        「★ **读数只能事后标记，不能阻断**」；★ 而本机制**只改下一轮的提示词**（★ 仍是事后）。
# ══════════════════════════════════════════════════════════════════
乱_阈值 = {"同一语义重复": 3, "未解释指代": 2, "时间压力词": 1, "冲突诉求": 1}
_压力词 = ("马上", "赶紧", "立刻", "来不及", "尽快", "今天就", "今晚", "截止",
         "必须今天", "越快越好", "急")
_冲突词 = ("但是", "可是", "又想", "同时想", "既想", "一方面", "另一方面", "纠结",
         "矛盾", "舍不得", "放不下")
_指代词 = ("它", "这个", "那个", "这件事", "那件事", "他们", "她们", "这些", "那些")
_去标点 = (" ", "\t", "\u3000", "，", "。", "！", "？", "；", "：", "、", ",", ".", ";",
         ":", "!", "?", "（", "）", "(", ")", "「", "」", "『", "』", "\"", "'",
         "\u201c", "\u201d", "\u2018", "\u2019", "\u2014", "\u2026", "-")


def _归一(s):
    """★ 只去空白与常见标点（★ 对齐形状，★ 不改字）。"""
    t = str(s or "")
    for ch in _去标点:
        t = t.replace(ch, "")
    return t


def _乱(msg):
    """★ 数四种「乱」的信号（★ **形状级** · ★ 不判语义）。返回 {名: 次数}。"""
    t = str(msg or "")
    句 = [x for x in t.replace("！", "。").replace("？", "。")
          .replace("?", "。").replace("!", "。").split("。") if x.strip()]
    归一 = [_归一(x) for x in 句 if _归一(x)]
    重复 = max((归一.count(u) for u in set(归一)), default=0)
    指代 = 0
    for x in 句:
        s = x.strip().lstrip("，,、 ")
        if s and s.startswith(_指代词):
            指代 += 1
    压力 = sum(t.count(w) for w in _压力词)
    冲突 = sum(t.count(w) for w in _冲突词)
    return {"同一语义重复": 重复, "未解释指代": 指代, "时间压力词": 压力, "冲突诉求": 冲突}


def _乱纪律(msg):
    """★ 返回 `(读数, 要注入的纪律)` —— ★ **读数是证据，注入是动作；两者分开。**"""
    读 = _乱(msg)
    到阈 = [k for k, v in 乱_阈值.items() if 读.get(k, 0) >= v]
    if not 到阈:
        return 读, []
    return 读, [
        "★★★ **服务端读数（不是你的自评）**：★ 这一问里数到了 —— " +
        " · ".join("{0} {1} 次（阈值 {2}）".format(k, 读[k], 乱_阈值[k]) for k in 到阈) + "。",
        "★★ 它意味着：★ 对方这一问**可能还没成形**（★ 反复说同一句 / ★ 指代没落 / "
        "被时间压着 / ★ 同时要两件相反的事）。",
        "★ 故**先做可看**：★ 把他那句原话**逐字**复述回去，★ **再动**；"
        "★ 面与路可以少给，★ **但别猜他的意思**。",
        "★★ 而**不许因为他乱就替他理清** —— ★ 整理是他的事，★ 你只把形状摆出来。",
    ]


# ══════════════════════════════════════════════════════════════════
# C 组 · 反-恒真对照（★ 2026-10-13 加 · ★ 出处：《优化建议》第 6 条）
#
#   ★ 建议原话：★「★ **每组有效读数至少配一次「没停、情况也过了」的记录** ·
#     ★★ **没有它，「能停」与"一直在停"在账上一样。**」
#
#   ★★ 我的做法（★ **零人工**）：★ **注入与否本身就是对照** ——
#     · 触发乱纪律的轮 ⇒ **「有动作」那一组**
#     · 未触发的轮     ⇒ **「没动作」那一组**
#     ★★★ 每轮把「注入过什么」写进账 ⇒ ★ **两类样本同账积累、天然可对读**。
#
#   ★★★★ 而**如实标它的性质**：★ 这是**代理对照**，★ **不是随机对照** ——
#     ★ 触发是按"乱"的阈值走的，★ **两组的输入本来就不一样** ⇒
#     ★★ **故它只能回答"这套机制有没有在动"，★ 不能回答"它有没有用"**
#       （★ 后者要**真人前后对读** · ★ 而那一半**不是机器能判的**）。
# ══════════════════════════════════════════════════════════════════
def _账对照():
    """★ 只读账：★ 「有动作 / 没动作」两类样本数（★ 供 `/api/health` 报出）。"""
    try:
        import session_log as _sl
        rows = _sl._rows()
    except Exception:                                        # noqa: BLE001
        return {"有动作": 0, "无动作": 0, "总计": 0}
    有 = sum(1 for r in rows if r.get("乱纪律"))
    无 = sum(1 for r in rows if r.get("乱") is not None and not r.get("乱纪律"))
    return {"有动作": 有, "无动作": 无, "总计": len(rows)}


if __name__ == "__main__":
    # ★★ 三行启动横幅一律 `flush=True` —— ★ 实测：被重定向到文件时（无 flush）**看不到**，
    #    ★ 而它正带着**相位指纹**（相干的最小可判条件）⇒ ★ 这是"坏得看不出来"的一种。
    print(f"拆解器（外发 · 最精简版）→ http://{HOST}:{PORT}", flush=True)
    print(f"  ★ 档位：**工作模式（默认）· 护根可开**（★ 界面勾选框决定 · ★ 每轮落账）", flush=True)
    print(f"  ★ 相位指纹（★ 只算**相位规则**那三条）：{PHASE_FP or '**未载到「相位规则」**'} · "
          f"场景指纹（★ 层位表）：{SCENE_FP or '**未载到**'}", flush=True)
    print(f"  ★ API Key 只从环境变量 `{KEY_ENV}` 读；当前：{'已设' if get_api_key() else '**未设**（/api/chat 会拒服务）'}", flush=True)
    if CONFIG_FILE_TAINTED:
        print(f"  ⚠️ `{CONFIG_FILE.name}` 仍含 api_key/sk- 字段 —— **本版已忽略它**；"
              f"请删掉那个字段，并把 `{KEY_ENV}` 设进环境变量。", flush=True)
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
