# -*- coding: utf-8 -*-
r"""dissector.pyw —— 「拆解器」的桌面窗口启动器（★ 双击桌面图标 / `启动.bat` = 调它）。

★★★ 为什么文件名是英文 `dissector.pyw`（★ 不是忘记改名）：
  · `启动.bat` 的铁律是**纯 ASCII**（★ cmd 按 GBK 读 bat ⇒ 中文字节必乱码）；
  · ⇒ ★ bat 要引用的文件名**必须是 ASCII** ⇒ 启动器取 ASCII 名 + `.pyw` 后缀
    （★ `.pyw` = 在资源管理器里双击它也走 pythonw，同样无黑窗）；
  · ★ **给人看的中文名在别处**：桌面图标叫「拆解器」（见 `创建桌面快捷方式.py`）。

★★★ 它存在的三条理由（★ 不是多此一举）：
  1. ★ **无黑窗**：快捷方式指向 `pythonw.exe` ⇒ 没有控制台窗口；
  2. ★ **独立窗口**：用 Edge/Chrome 的 `--app=` 开一个**无地址栏、无标签页、独立任务栏图标**
     的窗口 ⇒ 看起来是个桌面程序，不是一个网页；
  3. ★★ **起不来要看得见**：`pythonw` 会把 stdout/stderr 全丢掉 ⇒
     ★ 本层把"跑不起来"变成可见（写 `日志·拆解器.log` + 弹一个对话框说明）。

★ 用法：
  · 桌面快捷方式「拆解器」 —— 推荐（无黑窗）。首次用 `创建桌面快捷方式.py` 生成。
  · 或双击 `启动.bat`（同样走本层）。
  · 想让改了代码的服务重启：再双击时带 `--重启`，或设环境变量 `TASTART_FORCE_RESTART=1`。
  · 自测口子：`TASTART_SKIP_WINDOW=1` ⇒ 只起服务、不开窗。
"""
from __future__ import annotations

import ctypes
import datetime
import os
import pathlib
import socket
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
SERVER = HERE / "app" / "server.py"
LOGF = HERE / "日志·拆解器.log"
PORT = int(os.environ.get("ROOTTHINK_PORT") or 8394)
URL = "http://127.0.0.1:{0}/".format(PORT)

# ★ pythonw 起子进程时，不许闪出控制台窗口
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

# ★ 桌面窗口用什么开：优先 Edge（系统自带），退 Chrome，最后退默认浏览器
BROWSERS = [
    pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    pathlib.Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    pathlib.Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    pathlib.Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]


def _log(s: str) -> None:
    try:
        with LOGF.open("a", encoding="utf-8") as f:
            f.write("[{0}] {1}\n".format(
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), s))
    except OSError:
        pass


def _弹窗(标题: str, 内容: str) -> None:
    """失败时告知用户（★ 用 ctypes 的 MessageBoxW —— ★ 不创建 COM 对象）。"""
    try:
        ctypes.windll.user32.MessageBoxW(None, 内容, 标题, 0x40)
    except Exception:                                                          # noqa: BLE001
        pass


def _端口通(timeout_s: float) -> bool:
    """在 timeout 秒内轮询本地端口，能连上就 True（★ 只当参考，不当证据）。"""
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.4)
    return False


# ══════════════════════════════════════════════════════════════════════
# ★★ 「有没有人在听」不许用「能不能连上」判 —— ★ 出处：电商顾问那台踩过的坑
#    · 「端口有反应」证明的是**有个东西在听**，不是**跑的是现在这份代码**；
#    · 杀掉旧服务后 TIME_WAIT 里的残留连接会让"能连上"仍返回 True
#      ⇒ 重启路会把自己又送回"服务已在跑"那一支 ⇒ **新服务根本没起。**
#    ⇒ 故按**占用端口的进程**判（拿不到占用者时才退回"能连上"，且只当参考）。
# ══════════════════════════════════════════════════════════════════════
def _占端口者() -> dict:
    """返回 `{"pid","名字","起于"}` 或 `{}`（拿不到就空，不抛）。"""
    ps = ("$c = Get-NetTCPConnection -LocalPort {0} -State Listen -EA SilentlyContinue "
          "| Select-Object -First 1; "
          "if ($c) {{ $o = Get-Process -Id $c.OwningProcess -EA SilentlyContinue; "
          "if ($o) {{ '{{0}}|{{1}}|{{2}}' -f $o.Id, $o.ProcessName, "
          "$o.StartTime.ToString('yyyy-MM-dd HH:mm:ss') }} }}").format(PORT)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=12,
                           creationflags=_NOWIN)
    except Exception:                                                          # noqa: BLE001
        return {}
    out = [x for x in (r.stdout or "").strip().splitlines() if x.strip()]
    if not out:
        return {}
    p = out[-1].strip().split("|")
    if len(p) != 3 or not p[0].isdigit():
        return {}
    return {"pid": p[0], "名字": p[1], "起于": p[2]}


def _有人在听() -> bool:
    if _占端口者():
        return True
    return _端口通(0.2)          # ★ 退路：拿不到占用者时才用，且只当参考


def _杀占端口者(pid: str) -> bool:
    for 参数 in (["/PID", pid], ["/PID", pid, "/F"]):
        try:
            r = subprocess.run(["taskkill"] + 参数, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=15,
                               creationflags=_NOWIN)
            if r.returncode == 0:
                return True
        except Exception:                                                      # noqa: BLE001
            continue
    return False


def _服务比文件旧() -> str:
    """★ 三态：`'旧'` / `'新'` / `'测不了'`（★ 各带一句为什么）。

    ★★ `'测不了'` **不许被当成 `'新'`** —— ★ 那正是这条判据存在的理由。
    """
    who = _占端口者()
    if not who:
        return "测不了|拿不到占用端口的进程（无权限或缺 Get-NetTCPConnection）"
    try:
        t0 = datetime.datetime.strptime(who["起于"], "%Y-%m-%d %H:%M:%S").timestamp()
    except Exception:                                                          # noqa: BLE001
        return "测不了|占用者的起时读不出来（{0}）".format(who.get("起于"))
    try:
        t1 = SERVER.stat().st_mtime
    except OSError:
        return "测不了|读不到 {0} 的 mtime".format(SERVER.name)
    if t0 < t1:
        return ("旧|PID {0}（{1}）起于 {2}，而 {3} 改于 {4} ⇒ **跑的是旧代码**".format(
            who["pid"], who["名字"], who["起于"], SERVER.name,
            datetime.datetime.fromtimestamp(t1).strftime("%Y-%m-%d %H:%M:%S")))
    return "新|PID {0} 起于 {1}，晚于 {2} 的改动".format(who["pid"], who["起于"], SERVER.name)


def _找浏览器():
    for p in BROWSERS:
        if p.is_file():
            return p
    return None


def _开桌面窗口() -> None:
    if os.environ.get("TASTART_SKIP_WINDOW") == "1":
        _log("（自测口子）跳过开窗")
        return
    b = _找浏览器()
    if b is not None:
        # --app=独立窗口（无地址栏/无标签页） · --no-first-run 免首启向导
        subprocess.Popen([str(b), "--app=" + URL, "--no-first-run",
                          "--window-size=1180,860"],
                         creationflags=_NOWIN)
        _log("已开桌面窗口：{0} --app={1}".format(b.name, URL))
    else:
        _log("未找到 Edge/Chrome ⇒ 退回默认浏览器")
        os.startfile(URL)                                                      # noqa: S606


def _服务解释器() -> str:
    """★ 起服务用哪个解释器：**优先本包自带的 pythonw**（无黑窗）。"""
    for c in (HERE / "python" / "pythonw.exe", HERE / "python" / "python.exe"):
        if c.is_file():
            return str(c)
    return sys.executable


def main() -> int:
    _log("=== 启动拆解器：入口被点开 ===")
    if not SERVER.is_file():
        _log("** app\\server.py 不在：" + str(SERVER))
        _弹窗("拆解器 · 启动失败",
              "找不到 app\\server.py：\n" + str(SERVER) +
              "\n\n是不是把 app 文件夹删了或改了名？程序本体在里面。")
        return 2

    # ① 服务真的在跑？（★ 按占用者判，不按"能连上"）
    if _有人在听():
        v, why = _服务比文件旧().split("|", 1)
        if os.environ.get("TASTART_FORCE_RESTART") == "1" or "--重启" in sys.argv:
            who = _占端口者()
            if not who:
                _log("** 想重启，但拿不到占端口者")
                _弹窗("拆解器 · 重启失败",
                      "端口 {0} 有人在听，但拿不到它是谁。\n\n{1}\n\n"
                      "手动法：任务管理器结束 pythonw，或 taskkill /PID <号> /F".format(PORT, why))
                return 1
            _log("重启：结束 PID {0}（{1}）".format(who["pid"], who["名字"]))
            if not _杀占端口者(who["pid"]):
                _log("** 结束失败 PID {0}".format(who["pid"]))
                _弹窗("拆解器 · 重启失败",
                      "结束 PID {0} 失败。\n\n手动法：taskkill /PID {0} /F".format(who["pid"]))
                return 1
            for _ in range(30):
                if not _有人在听():
                    break
                time.sleep(0.4)
            if _有人在听():
                _log("** 旧服务 12 秒仍未停干净 ⇒ 不起新的（免得两个抢端口）")
                _弹窗("拆解器 · 重启未完成",
                      "结束了 PID {0}，但 {1} 端口上**仍然有人听**。\n\n"
                      "手动法：`taskkill /PID {0} /F` 后再双击。".format(who["pid"], PORT))
                return 1
            _log("旧服务已停 ⇒ 继续往下起新的")
            # ★ 关键：这里**直接往下走**去起服务（★ 别掉回"开窗口"那一支）
        elif v == "旧":
            _log("** " + why)
            _弹窗("拆解器 · 跑的是旧代码",
                  "端口 {0} 上那个服务，比 {1} 旧：\n\n{2}\n\n"
                  "⇒ 你双击图标**不会**加载新代码（这一层检测到有人在听就直接开窗口）。\n\n"
                  "要让它生效：再双击时带 `--重启`，或设环境变量 TASTART_FORCE_RESTART=1，\n"
                  "或手动 `taskkill /PID {3} /F` 后再双击。".format(
                      PORT, SERVER.name, why, _占端口者().get("pid", "?")))
            _开桌面窗口()
            return 0
        else:
            if v == "测不了":
                _log("（注意）" + why + " ⇒ 按旧行为开窗口")
            _log("服务已在跑（{0} 有人在听）⇒ 不重复起，直接开窗口".format(PORT))
            _开桌面窗口()
            return 0

    # ② 起服务（★ 用自带 pythonw ⇒ 无黑窗；输出重定向到日志）
    cmd = [_服务解释器(), str(SERVER)]
    _log("命令：" + " ".join(cmd))
    try:
        with LOGF.open("a", encoding="utf-8") as lf:
            proc = subprocess.Popen(cmd, cwd=str(HERE / "app"),
                                    stdout=lf, stderr=subprocess.STDOUT,
                                    creationflags=_NOWIN)
        _log("已起子进程 pid={0}".format(proc.pid))
    except Exception as e:                                                     # noqa: BLE001
        _log("** 起服务异常：" + repr(e))
        _弹窗("拆解器 · 异常", "起服务时出错：\n{0}\n\n日志：\n{1}".format(e, LOGF))
        return 1

    # ③ 6 秒内退出 = 起失败 ⇒ 读日志尾巴弹给用户（★ 不静默）
    try:
        rc = proc.wait(timeout=6)
    except subprocess.TimeoutExpired:
        _log("★ 6 秒内未退出 ⇒ 服务在跑")
    else:
        tail = ""
        try:
            tail = "\n".join(LOGF.read_text(encoding="utf-8", errors="replace").splitlines()[-8:])
        except Exception:                                                      # noqa: BLE001
            pass
        _log("** 子进程早早退出 rc={0}".format(rc))
        _弹窗("拆解器 · 起不来",
              "服务启动即退出（rc={0}）。\n\n日志末尾：\n{1}\n\n完整日志：\n{2}"
              .format(rc, tail, LOGF))
        return 1

    # ④ 等端口真通（最多再等 12 秒），再开桌面窗口
    if not _端口通(12):
        _log("** 端口 12 秒未通 ⇒ 不开窗（服务可能没起成）")
        _弹窗("拆解器 · 未就绪",
              "服务起了但 {0} 端口一直没通。\n\n日志：\n{1}".format(PORT, LOGF))
        return 1
    _log("★ 端口已通 ⇒ 开桌面窗口")
    _开桌面窗口()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
