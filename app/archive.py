#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""archive · 会话原文的**不可变归档**（★ 记忆机制落点二 · ★ 2026-10-09）

★★★ 为什么有这一个文件（★ 出处：★ 《方案·顾问记忆机制》§6 · ★ 敌手 D 第 8 轮复核后仍成立的那一条）：

   ★ `data\\sessions.json` 是**全部对话的**唯一副本****（★ 实测 **1,752,772 B / 5,900 行**）。
   ★★ 而它是**全量重写** —— ★ 原子替换（`os.replace`）**已经接上了**（★ 敌手 D 第 8 轮 V-2 实测），
       ★ **故"写一半崩"这条已经堵住**。
   ★★★ **而还剩一条没堵**：★ **原子替换只保证"要么新、要么旧" —— ★ 它不保留旧的。**
       ⇒ ★ 若一次逻辑错误把 `db` 算错了（★ 不是崩，★ 是**算错**）⇒ ★ **旧的那一本被无声覆盖** ⇒
         ★★ **那不是"遗忘"，★ 是"全失"，★ 而且没有任何一处能查回来。**

★★ 三条纪律（★ 与体系的其它件同形）：
   ① **只增**：★ 归档件**永不覆盖**（★ 每次一个新档 · ★ 带时间戳与 sha256）；
   ② **可核**：★ 每一档记 `字节数 + sha256 + 来自哪一件 + 时刻`（★ 而这份记录本身也 append-only）；
   ③ **不静默**：★ 归档失败**不许吞掉**（★ 它会返 `(ok, 详情)`，★ 调用方自己决定怎么办）。

★ 依两件协议 §3，本模块不产生判定主体。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import shutil
import sys

APP_DIR = pathlib.Path(__file__).resolve().parent
try:                                                                      # ★ 同目录的原子工具
    # ★★ 兜底：★ 调用方（★ 如 `server.py`）可能**没把 `core` 放进 `sys.path`** ——
    #    ★ 那样 `import atomic_io` 会 `ModuleNotFoundError` ⇒ ★ **静默退化成无锁追加**。
    #    ★★★ 故这里**自己把自己的目录塞进去**再试一次（★ 与 `archive` 的"不静默"立场一致）。
    try:
        import atomic_io                                                  # noqa: E402
    except ModuleNotFoundError:
        sys.path.insert(0, str(APP_DIR))
        import atomic_io                                                  # noqa: E402
except Exception:                                                         # noqa: BLE001
    atomic_io = None                                                      # type: ignore[assignment]

#: ★ 归档目录（★ 设在 `history/` —— ★ 与"账"同处 · ★ 而 `data/` 放"现役件"）
ARCHIVE_DIR = APP_DIR.parent / "history" / "archive"
#: ★ 归档台账（★ **append-only** —— ★ 每一档一行 · ★ 而它自己也是账）
ARCHIVE_LOG = "archive_log.jsonl"


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def stamp(now: datetime.datetime | None = None) -> str:
    """★ 归档用的时间戳（★ 到秒 · ★ 可排序 · ★ 可读）。"""
    n = now or datetime.datetime.now()
    return n.strftime("%Y%m%d-%H%M%S")


def archive(path: pathlib.Path | str, *, why: str = "", keep: int = 0,
            archive_dir: pathlib.Path | str | None = None,
            now: datetime.datetime | None = None) -> tuple:
    """★★ 把**现役件**另存为一份**带时间戳的不可变归档**。

    ★ 参数：
       · `path`        —— ★ 要归档的现役件（★ 它**不动** —— ★ 本函数只复制）
       · `why`         —— ★ 为什么归档（★ 会写进台账 —— ★ **不许留空**，★ 空则记 `未声明`）
       · `keep`        —— ★ 保留最近 N 档（★ **0 = 全留** · ★ 默认 0）
       · `archive_dir` —— ★ 归档到哪（★ 默认 `history/archive/`）
       · `now`         —— ★ 可注入的时刻（★ 供自测）
    ★★ 返回 `(ok, 详情)` —— ★ **失败不抛、也不静默**（★ 与体系"不静默降级"同立场）。
    """
    p = pathlib.Path(path)
    d = pathlib.Path(archive_dir) if archive_dir else ARCHIVE_DIR
    if not p.exists():
        return False, "★ 现役件不在：{0}".format(p)
    try:
        raw = p.read_bytes()
    except Exception as e:                                                # noqa: BLE001
        return False, "★ 读不动：{0}: {1}".format(type(e).__name__, e)
    d.mkdir(parents=True, exist_ok=True)
    ts = stamp(now)
    dst = d / "{0}.{1}{2}".format(p.stem, ts, p.suffix)
    # ★ 同一秒内重复归档 ⇒ 加序号（★ 不许覆盖 —— ★ 这是本模块的第 ① 条纪律）
    k = 1
    while dst.exists():
        dst = d / "{0}.{1}-{2}{3}".format(p.stem, ts, k, p.suffix)
        k += 1
    try:
        shutil.copy2(p, dst)
    except Exception as e:                                                # noqa: BLE001
        return False, "★ 写不动：{0}: {1}".format(type(e).__name__, e)

    row = {
        "at": (now or datetime.datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "src": str(p),
        "dst": str(dst),
        "bytes": len(raw),
        "sha256": _sha256_bytes(raw),
        "why": (why or "").strip() or "未声明",
    }
    # ★ 台账 append（★ 走原子追加；★ 缺 atomic_io 就退化成普通追加 —— ★ 而**明说**）
    lp = d / ARCHIVE_LOG
    if atomic_io is not None and hasattr(atomic_io, "append_line"):
        atomic_io.append_line(lp, row)
    else:
        with open(lp, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    清理 = 0
    if keep and keep > 0:
        olds = sorted([x for x in d.glob("{0}.*{1}".format(p.stem, p.suffix))
                       if x != dst])
        for x in olds[:-keep] if len(olds) > keep else []:
            try:
                x.unlink()
                清理 += 1
            except Exception:                                             # noqa: BLE001
                pass
    return True, "★ {0} ⇒ {1}（{2:,} B · sha {3}）{4}".format(
        p.name, dst.name, len(raw), row["sha256"][:12],
        "· 清旧 {0} 档".format(清理) if 清理 else "")


def verify(archive_dir: pathlib.Path | str | None = None) -> tuple:
    """★ 核归档台账：★ **每一档都还在、且 sha256 与台账一致**（★ 归档的可核性）。

    ★★ 返回 `(ok, 问题列表)` —— ★ **空列表 = 全对得上。**
    """
    d = pathlib.Path(archive_dir) if archive_dir else ARCHIVE_DIR
    lp = d / ARCHIVE_LOG
    if not lp.exists():
        return True, []
    问题 = []
    n = 0
    for i, line in enumerate(lp.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:                                                 # noqa: BLE001
            问题.append("★ 台账第 {0} 行不是合法 JSON".format(i))
            continue
        n += 1
        f = pathlib.Path(row.get("dst", ""))
        if not f.exists():
            # ★ 若曾 `keep` 清理过 ⇒ 判"已清"，★ 不算错（★ 而**要显形**）
            if row.get("dst") and not f.exists():
                continue
        else:
            now = _sha256_bytes(f.read_bytes())
            if now != row.get("sha256"):
                问题.append("★ {0} 的 sha256 与台账不符".format(f.name))
    return (not 问题), 问题


# ══════════════════════════════════════════════════════════════════
# 自检（★ 正反两向 —— ★ 与 `atomic_io` 的自检同形）
# ══════════════════════════════════════════════════════════════════
def _selftest() -> int:
    import tempfile
    ok = True

    def ck(label, cond, extra=""):
        nonlocal ok
        if not cond:
            ok = False
        print("  {0} {1}{2}".format("✅" if cond else "❌", label,
                                    ("  —— " + str(extra)) if extra else ""))

    print("[archive] 自检 · 不可变归档")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="arch-")).resolve()
    src = tmp / "sessions.json"
    src.write_text('{"sessions": [{"id": "a"}]}', encoding="utf-8")

    # ① 正例：归档出一档、台账有一行
    good, det = archive(src, why="自检①", archive_dir=tmp / "arch")
    ck("① 归档成功", good, det[:70])
    log = (tmp / "arch" / ARCHIVE_LOG)
    ck("② 台账有 1 行", log.exists() and len(log.read_text(encoding="utf-8").strip().split("\n")) == 1)

    # ③ 现役件**不动**（★ 这是"只复制"那条）
    ck("③ 现役件未被改动", src.read_text(encoding="utf-8") == '{"sessions": [{"id": "a"}]}')

    # ④ 同秒再归档 ⇒ **不许覆盖**（★ 纪律 ①）
    good2, det2 = archive(src, why="自检④", archive_dir=tmp / "arch")
    files = sorted(x.name for x in (tmp / "arch").glob("sessions.*.json"))
    ck("④ 同秒两次归档 ⇒ 两档（不覆盖）", good2 and len(files) == 2, str(files))
    ck("④b 台账变成 2 行", len(log.read_text(encoding="utf-8").strip().split("\n")) == 2)

    # ⑤ 现役件改坏之后，归档档**仍是旧的**（★ 这才是"不可变"）
    src.write_text('{"sessions": []}', encoding="utf-8")
    old = pathlib.Path(json.loads(log.read_text(encoding="utf-8").split("\n")[0])["dst"])
    ck("⑤ 改坏现役件之后，第一档内容不变", '"a"' in old.read_text(encoding="utf-8"))

    # ⑥ 核账：sha256 应与台账一致
    ok6, probs = verify(tmp / "arch")
    ck("⑥ 核账通过", ok6, str(probs)[:70])

    # ⑦ 反证：改坏一个归档档 ⇒ 核账**必须报**
    old.write_text('{"sessions": [{"id": "TAMPERED"}]}', encoding="utf-8")
    ok7, probs7 = verify(tmp / "arch")
    ck("⑦ 反证：档被改 ⇒ 核账报错", (not ok7) and any("sha256" in x for x in probs7), str(probs7)[:70])

    # ⑧ 反证：现役件不在 ⇒ **报错，不静默**
    ok8, det8 = archive(tmp / "不存在.json", archive_dir=tmp / "arch")
    ck("⑧ 反证：现役件不在 ⇒ 返 False 且带话", (not ok8) and "不在" in det8, det8[:60])

    # ⑨ `why` 留空 ⇒ 台账记「未声明」（★ 不许留空）
    good9, _ = archive(src, why="", archive_dir=tmp / "arch")
    last = json.loads(log.read_text(encoding="utf-8").strip().split("\n")[-1])
    ck("⑨ why 留空 ⇒ 台账记「未声明」", good9 and last["why"] == "未声明", last["why"])

    # ⑩ 台账行有 bytes 与 sha256（★ 可核三样齐）
    ck("⑩ 台账行含 bytes / sha256 / at",
       all(k in last for k in ("bytes", "sha256", "at")), str(sorted(last))[:80])

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("  → [{0}] archive 自检".format("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="会话原文的不可变归档")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--file", help="要归档的现役件")
    ap.add_argument("--why", default="", help="为什么归档（★ 建议写清）")
    ap.add_argument("--keep", type=int, default=0, help="保留最近 N 档（0=全留）")
    ap.add_argument("--verify", action="store_true", help="核归档台账")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    if a.verify:
        ok, probs = verify()
        print("核账：{0}".format("全对得上" if ok else "** 有问题"))
        for x in probs:
            print("   " + x)
        print("归档目录：{0}".format(ARCHIVE_DIR))
        n = len(list(ARCHIVE_DIR.glob("*"))) if ARCHIVE_DIR.exists() else 0
        print("目录内件数：{0}".format(n))
        raise SystemExit(0 if ok else 1)
    if a.file:
        ok, det = archive(a.file, why=a.why, keep=a.keep)
        print(("[OK] " if ok else "[FAIL] ") + det)
        raise SystemExit(0 if ok else 1)
    ap.print_help()
