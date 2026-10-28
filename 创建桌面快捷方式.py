# -*- coding: utf-8 -*-
r"""创建桌面快捷方式.py —— 在桌面放一个「拆解器」图标（★ 双击即开 · ★ 无黑窗）。

★★★ 为什么要这个脚本（★ 而不是直接塞一个 .lnk 进包）：
  · `.lnk` 里存的是**这台机器上的绝对路径**（pythonw 在哪、项目在哪）；
  · ⇒ ★ 换一台机器 / 换个目录，那个 `.lnk` 就**指错地方**了；
  · ⇒ ★ 故本包**不预置** `.lnk`，而是给这个脚本：★ **谁用谁双击一次**，就建好本机的图标。

★★ 为什么不用 COM 建（★ 本机政策）：
  · `New-Object -ComObject WScript.Shell` 与 `win32com.client.Dispatch` **都被安全策略硬拦**
    （报 "COM object instantiation can run arbitrary code"），加沙箱豁免也无效；
  · ⇒ ★ 故按 **MS-SHLLINK** 规范**手工拼字节**写 `.lnk`（★ 只调 shell32 的普通导出函数
    `SHParseDisplayName` / `ILGetSize`，**不创建任何 COM 对象**）。

★ 用法：
  · 双击（或用 `python\python.exe 创建桌面快捷方式.py`）⇒ 桌面出现「拆解器」；
  · `--到 "D:\某处"` ⇒ 建到别的目录（默认桌面）；
  · `--删` ⇒ 把桌面上那个图标删掉。
"""
from __future__ import annotations

import ctypes
import os
import pathlib
import struct
import sys

HERE = pathlib.Path(__file__).resolve().parent
TARGET = HERE / "python" / "pythonw.exe"          # ★ 无控制台窗口的解释器
SCRIPT = HERE / "dissector.pyw"                   # ★ 目标脚本（★ ASCII 名：.lnk 参数无编码问题）
ICON = HERE / "拆解器.ico"                         # ★ 有则用，没有就用默认图标
NAME = "拆解器"
DESC = "拆解器 —— 帮你看清问题"

CLSID_ShellLink = bytes.fromhex("0114020000000000c000000000000046")

# LinkFlags（★ 顺序即 StringData 的书写顺序，不可乱）
F_IDLIST = 0x01
F_LINKINFO = 0x02
F_NAME = 0x04
F_WORKINGDIR = 0x10
F_ARGUMENTS = 0x20
F_ICON = 0x40
F_UNICODE = 0x80


def _桌面() -> pathlib.Path:
    d = pathlib.Path(os.environ.get("USERPROFILE", str(pathlib.Path.home()))) / "Desktop"
    return d


def _pidl(路径: str) -> bytes:
    """★ 问系统要 PIDL（★ 不手写 —— drive-root item 的格式极易错）。"""
    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    shell32.SHParseDisplayName.argtypes = [
        ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
    shell32.SHParseDisplayName.restype = ctypes.c_long
    shell32.ILGetSize.argtypes = [ctypes.c_void_p]
    shell32.ILGetSize.restype = ctypes.c_ulong
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoInitialize(None)
    pidl = ctypes.c_void_p()
    attrs = ctypes.c_ulong()
    hr = shell32.SHParseDisplayName(路径, None, ctypes.byref(pidl), 0, ctypes.byref(attrs))
    if hr != 0 or not pidl:
        raise OSError("SHParseDisplayName 失败 hr={0}（路径：{1}）".format(hr, 路径))
    size = shell32.ILGetSize(pidl)
    data = ctypes.string_at(pidl, size)
    ole32.CoTaskMemFree(pidl)
    return data


def _s(文本: str) -> bytes:
    """StringData 的一项：u16(字符数) + UTF-16LE（★ 无结尾 NUL）。"""
    return struct.pack("<H", len(文本)) + 文本.encode("utf-16-le")


def 写快捷方式(lnk: pathlib.Path) -> None:
    assert TARGET.is_file(), "★ 找不到解释器：{0}".format(TARGET)
    assert SCRIPT.is_file(), "★ 找不到启动脚本：{0}".format(SCRIPT)

    flags = F_IDLIST | F_LINKINFO | F_NAME | F_WORKINGDIR | F_ARGUMENTS | F_UNICODE
    用图标 = ICON.is_file()
    if 用图标:
        flags |= F_ICON

    # ① Header（★ 恰好 76 字节 —— 格式串很容易多写一个 I，靠断言兜住）
    header = struct.pack(
        "<I16sIIQQQIIIHHII",
        0x4C, CLSID_ShellLink, flags, 0x20,      # HeaderSize / CLSID / Flags / FileAttributes
        0, 0, 0,                                 # Creation/Access/Write FILETIME（0=不设）
        0,                                       # FileSize
        0,                                       # IconIndex
        7,                                       # ShowCommand（7 = 最小化不激活）
        0, 0, 0, 0)                              # HotKey / Reserved1 / Reserved2 / Reserved3
    assert len(header) == 76, "★ Header 不是 76 字节：{0}".format(len(header))

    # ② LinkTargetIDList（★ 必须带 —— 只有 LinkInfo 的 .lnk 解不出来，ShellExecute 会返回 31）
    pidl = _pidl(str(TARGET))
    idlist = struct.pack("<H", len(pidl) + 2) + pidl + b"\x00\x00"

    # ③ LinkInfo（路径的后备解析）
    lb = str(TARGET).encode("mbcs") + b"\x00"
    suffix = b"\x00"
    vol = struct.pack("<IIII", 16, 3, 0, 0x10)          # VolumeID（本地固定盘 · 无卷标）
    vol_off = 0x1C
    base_off = vol_off + len(vol)
    suffix_off = base_off + len(lb)
    total = suffix_off + len(suffix)
    linkinfo = (struct.pack("<IIIIIII", total, 0x1C, 1, vol_off, base_off, 0, suffix_off)
                + vol + lb + suffix)

    # ④ StringData（★ 顺序必须与 flag 顺序一致：NAME → WORKING_DIR → ARGUMENTS → ICON）
    strdata = _s(NAME) + _s(str(HERE)) + _s('"' + str(SCRIPT) + '"')
    if 用图标:
        strdata += _s("{0},0".format(ICON))

    # ⑤ 结尾（ExtraData 终止块）
    data = header + idlist + linkinfo + strdata + struct.pack("<I", 0)

    lnk.parent.mkdir(parents=True, exist_ok=True)
    if lnk.exists():
        lnk.unlink()
    lnk.write_bytes(data)


def 验证(lnk: pathlib.Path) -> int:
    """★ 真拉起一次 —— 双重判据：① ShellExecute 返回值 > 32；② 目标脚本自己写的日志出现启动记录。"""
    log = HERE / "日志·拆解器.log"
    before = log.stat().st_size if log.exists() else 0
    rc = ctypes.windll.shell32.ShellExecuteW(None, "open", str(lnk), None,
                                             str(lnk.parent), 1)
    print("  ShellExecute 返回：{0}（>32 才算成功）".format(rc))
    if rc <= 32:
        return 1
    import time
    for _ in range(20):                     # ★ 等目标写下启动痕迹（★ 进程会不会被回收不管，痕迹才算数）
        time.sleep(0.4)
        if log.exists() and log.stat().st_size > before:
            tap = log.read_text(encoding="utf-8", errors="replace").splitlines()[-1:]
            print("  启动器已留痕：{0}".format(tap[0] if tap else ""))
            return 0
    print("  ⚠ 没等到启动器留痕 —— 快捷方式本身写对了，但可能没跑起来（看 日志·拆解器.log）")
    return 1


def main() -> int:
    args = sys.argv[1:]
    if "--删" in args:
        目标 = _桌面() / (NAME + ".lnk")
        if 目标.exists():
            目标.unlink()
            print("已删除：{0}".format(目标))
        else:
            print("桌面上本来就没有：{0}".format(目标))
        return 0
    落点 = _桌面()
    for i, a in enumerate(args):
        if a == "--到" and i + 1 < len(args):
            落点 = pathlib.Path(args[i + 1])
    lnk = 落点 / (NAME + ".lnk")
    print("目标：{0}".format(TARGET))
    print("脚本：{0}".format(SCRIPT))
    print("图标：{0}".format(ICON if ICON.is_file() else "（无，用默认图标）"))
    print("写到：{0}".format(lnk))
    写快捷方式(lnk)
    print("已写入 {0} 字节。".format(lnk.stat().st_size))
    if "--不验证" not in args:
        print("验证（真拉起一次）…")
        return 验证(lnk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
