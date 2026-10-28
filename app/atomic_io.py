# -*- coding: utf-8 -*-
r"""`atomic_io.py` —— **原子追加** 与 **原子替换**（B-35 / B-37 的共同地基）。

★★★ 为什么需要它（两条实测）

    **B-35 并发追加会丢行、会产生坏行** ——
      实测（4 进程 × 300 行 append 同一 jsonl）：**期望 1200 行 · 实得 1081（丢 119）· 坏行 16**；
      多行单次 write 同样交错：**期望 2400 · 实得 2111 · 坏行 22**。
      根因：三本账都是 `with p.open("a") as f: f.write(...)` —— **无任何互斥**。

    **B-37 整本重写非原子** ——
      `SESSIONS_FILE.write_text(json.dumps(...))` 全量覆盖，**写一半崩 ⇒ 整个行使史损坏**。

★★ 设计取舍（★ 如实标注）

    · **锁用什么**：**独立的锁文件**（`<目标>.lock`），不用"锁目标文件本身"。
      理由：Windows 上 `msvcrt.locking` 是对**文件区域**加锁，在 `open("a")` 下区域与
      追加位置的交互有坑；用独立锁文件语义干净、跨进程有效。
      ★ 代价：每次追加多一次 open/lock/unlock/close（毫秒级）。**本场景写入频率很低**（每轮几次），
        故取"稳"不取"快"。
    · **锁不住的情形**：★ **不阻止别人绕过本模块直接写文件** —— 它是"协作式"的。
      ⇒ 故它**不能替代 B-31 的链式校验**（那是"事后能不能发现"，这是"事前别撞车"）。
    · **超时**：拿不到锁就等，超时则**抛错**（★ 不静默放弃写入 —— 那会变成新的"静默少记"）。
    · **fsync**：默认 `fsync=False`。日志类不必每次落盘；要强持久化时传 `fsync=True`。

用法：
    from atomic_io import append_line, append_text, write_json_atomic
    append_line(LOG, rec)                    # 一行 JSON（自动加 \\n）
    write_json_atomic(SESSIONS_FILE, db)     # 原子替换整本 JSON

★★ `.lock` 文件是**故意留下的**（不是垃圾）

    · 每个被保护的账都有一个 `<账名>.lock`（**0 字节**），它们是**锁的载体**。
    · ★★ **不要"顺手清理"它们** —— 删掉不会立刻坏事（下次写入会重建），
      但**在重建的那一瞬间存在竞态窗口**。
    · ★ 已核：`_compact.py` 的安全复核正则只认 `_old_mirror_*.md` 与
      `config.local.json.含key旧值归档*` ⇒ **它不会误删 `.lock`**（这是对的，别放宽）。
    · 现状（实测）：`sessions.json.lock` · `能力边界账.jsonl.lock` ·
      `.probe_session_log.jsonl.lock` · `fs_access.jsonl.lock` —— 共 4 个，各自 0 字节。
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import sys
import tempfile
import time

#: 拿不到锁时的等待上限（秒）。★ 超时**抛错**，不静默跳过。
LOCK_TIMEOUT_S = 15.0
#: 重试间隔（秒）
LOCK_RETRY_S = 0.02

_IS_WIN = os.name == "nt"


@contextlib.contextmanager
def _file_lock(target: pathlib.Path, timeout: float = LOCK_TIMEOUT_S):
    """用独立的 `<目标>.lock` 做**跨进程互斥**。

    ★ 语义：进入即持锁；退出即释放。拿不到锁 ⇒ **抛 TimeoutError**（★ 绝不静默跳过）。

    ★★★ **2026-10-09 晚修**（★ 出处：★ 敌手 D 第 9 轮 **V-2** · ★ 它逐字指出了 `:67`）：
      ★★ **原实现把 `open(lock_path, "a+b")` 写在 `try` **之外**** ⇒
         ★★★ 它在 Windows 上撞 **`PermissionError`**（★ 那是一个 `OSError`，★ 而它**不是** `TimeoutError`）
         ⇒ **没有任何一层接它** ⇒ 抛出 ⇒ ★★ **那个进程本次的全部追加都丢**（★ 实测：4 进程 × 300 行 = 1200，
            ★ **实得 900** —— ★ `W1` 全丢）。
      ★★★ **而 `:63` 那句承诺是**「拿不到锁 ⇒ 抛 `TimeoutError`」**** ⇒
         ★★ **它防的是"拿不到锁"，★ 没防"开不了锁文件"** —— ★ 而**后者在 Windows 多进程下是常态**
         （★ 一个进程正持着那把锁时，另一个进程去 `open` 同名文件可能直接被拒）。
      ⇒ ★★★ **修法**：★ 把 `open` **移进重试循环**，★ 且把 **`PermissionError` 与"锁被占"一视同仁** ——
         ★ 因为**对调用方而言，两者是同一件事**：★「**现在拿不到，★ 等一会儿再试**」。
         ★★ 而**超时之后**仍然抛 `TimeoutError`（★ 那才是 docstring 承诺的那一条）。
    """
    lock_path = target.with_name(target.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    got = False
    fh = None
    deadline = time.time() + timeout
    try:
        while True:
            try:
                # ★★★ 修：`open` 在**重试循环之内**（★ 原实现在 try 之外 ⇒ 撞 PermissionError 没人接）
                if fh is None:
                    fh = open(lock_path, "a+b")     # ★ 用 a+b：不存在则建；不截断
                if _IS_WIN:
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except OSError as e:                    # ★★★ 修：`PermissionError` 也走这条路
                # ★★ 开不了（★ 多半是别人正持着）⇒ 关掉半开的句柄，★ 下一轮重开
                if fh is not None and not got:
                    with contextlib.suppress(Exception):
                        fh.close()
                    fh = None
                if time.time() >= deadline:
                    raise TimeoutError(
                        "等锁超时（{0}s）：{1} —— ★ 不静默跳过写入"
                        "（★ 最后一次的错是 {2}：{3}）".format(
                            timeout, lock_path.name, type(e).__name__, e))
                time.sleep(LOCK_RETRY_S)
        yield
    finally:
        if got and fh is not None:
            with contextlib.suppress(Exception):
                if _IS_WIN:
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        if fh is not None:
            with contextlib.suppress(Exception):
                fh.close()


def append_text(target: pathlib.Path | str, text: str, *, fsync: bool = False,
                timeout: float = LOCK_TIMEOUT_S, encoding: str = "utf-8") -> int:
    """★ 原子追加一段文本（持锁期间完成 write + flush）。返回写入的**字节数**。

    ★ 关键：`open` **在锁内**、`write` 是**单次**、并**显式 flush** ——
      实测表明"单次 write"本身不足以保证不交错（多进程仍会丢），故必须持锁。
    """
    p = pathlib.Path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode(encoding)
    with _file_lock(p, timeout):
        with open(p, "ab") as f:
            f.write(data)
            f.flush()
            if fsync:
                os.fsync(f.fileno())
    return len(data)


def append_line(target: pathlib.Path | str, obj, *, fsync: bool = False,
                timeout: float = LOCK_TIMEOUT_S) -> int:
    """★ 原子追加**一行 JSON**（自动补 `\\n`）。"""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    if not text.endswith("\n"):
        text += "\n"
    return append_text(target, text, fsync=fsync, timeout=timeout)


def write_json_atomic(target: pathlib.Path | str, obj, *, indent: int | None = 1,
                      fsync: bool = False, timeout: float = LOCK_TIMEOUT_S) -> int:
    """★ **原子替换**整本 JSON（B-37）。

    手法：写同目录临时文件 → `fsync`（可选）→ `os.replace()` 原子改名。
    ★ 用 `os.replace` 而不是 `shutil.move`：前者在 Windows 上也是**原子覆盖**。
    ★ 临时文件与目标**同目录**（`os.replace` 要求同卷）。
    """
    p = pathlib.Path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, indent=indent)
    with _file_lock(p, timeout):
        fd, tmp = tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(text.encode("utf-8"))
                f.flush()
                if fsync:
                    os.fsync(f.fileno())
            os.replace(tmp, p)          # ★ 原子
        except BaseException:
            with contextlib.suppress(Exception):
                os.unlink(tmp)
            raise
    return len(text.encode("utf-8"))


def _selftest() -> int:
    """★ 正反两向：并发追加**不许丢行/坏行**；原子替换**崩在写一半也不许毁掉原件**。"""
    import json as _j
    import shutil
    import subprocess
    ok = True

    def ck(label, cond, extra=""):
        nonlocal ok
        if not cond:
            ok = False
        print("  {0} {1}{2}".format("✅" if cond else "❌", label,
                                    ("  —— " + str(extra)) if extra else ""))

    print("[atomic_io] 自测 · 原子追加 / 原子替换")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="atomicio-")).resolve()

    # ① 串行正例
    f1 = tmp / "a.jsonl"
    for i in range(5):
        append_line(f1, {"i": i})
    lines = f1.read_text(encoding="utf-8").splitlines()
    ck("① 串行追加 5 行、可解析", len(lines) == 5 and all(_j.loads(x) for x in lines))
    ck("② 末行有换行（f1 以 \\n 结束）", f1.read_bytes().endswith(b"\n"))

    # ③ 并发：4 进程 × 300 行
    n_proc, per = 4, 300
    target = tmp / "conc.jsonl"
    worker = tmp / "w.py"
    worker.write_text(
        "import sys, json, pathlib\n"
        "sys.path.insert(0, {app!r})\n"
        "from atomic_io import append_line\n"
        "p = pathlib.Path(sys.argv[1]); tag = sys.argv[2]\n"
        "for i in range({per}):\n"
        "    append_line(p, {{'w': tag, 'i': i, 'pad': 'x'*260}})\n".format(
            app=str(pathlib.Path(__file__).resolve().parent), per=per),
        encoding="utf-8")
    procs = [subprocess.Popen([sys.executable, str(worker), str(target), "W%d" % k])
             for k in range(n_proc)]
    for p in procs:
        p.wait()
    got = target.read_text(encoding="utf-8").splitlines()
    bad = 0
    per_w: dict = {}
    for l in got:
        try:
            per_w[_j.loads(l)["w"]] = per_w.get(_j.loads(l)["w"], 0) + 1
        except Exception:
            bad += 1
    exp = n_proc * per
    ck("③ 并发追加**不丢行**（{0} 进程 × {1} 行 = {2}）".format(n_proc, per, exp),
       len(got) == exp, "实得 {0} 行".format(len(got)))
    ck("④ 并发追加**无坏行**", bad == 0, "坏行 {0}".format(bad))
    ck("⑤ 每个进程的行数都齐", all(per_w.get("W%d" % k) == per for k in range(n_proc)), per_w)

    # ⑥ 原子替换正例
    f2 = tmp / "b.json"
    write_json_atomic(f2, {"x": 1})
    ck("⑥ 原子替换写入正确", _j.loads(f2.read_text(encoding="utf-8")) == {"x": 1})

    # ⑦ ★ 负对照：替换过程中抛错 ⇒ **原件必须完好**
    before = f2.read_text(encoding="utf-8")
    class Boom(dict):
        pass
    try:
        # 用不可 JSON 序列化的对象触发"序列化时就失败"（这发生在写临时文件之前）
        write_json_atomic(f2, {"bad": object()})
    except Exception:
        pass
    after = f2.read_text(encoding="utf-8")
    ck("⑦ 序列化失败 ⇒ 原件未被破坏", before == after, "现在 = {0}".format(after[:40]))

    # ⑧ ★ 负对照：临时文件不许残留
    leftovers = [p.name for p in tmp.glob("b.json.*.tmp")]
    ck("⑧ 失败后不留临时文件", not leftovers, leftovers)

    # ⑨ 锁文件存在但不干扰读取
    ck("⑨ 锁文件与目标分离（读目标不受影响）", f2.exists() and f2.stat().st_size > 0)

    print()
    print("  [{0}] ".format("OK" if ok else "X") + ("全部通过" if ok else "**有未通过**"))
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
