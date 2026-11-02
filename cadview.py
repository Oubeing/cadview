#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""cadview — 基于 cutsim 的 STEP / STL 查看、绕坐标轴旋转、导出工具。

架构
----
浏览器（three.js 前端）  <--HTTP-->  本地服务（Python）  -->  cutsim / OpenCASCADE
                                        │
                                        ├ STEP/STL/OBJ 导入
                                        ├ 绕 X/Y/Z 轴旋转
                                        └ 导出 STEP / STL

界面用浏览器渲染（离线：three.js 已随包内置），服务端只监听 127.0.0.1，
并带一次性 token，避免同机其它进程误调。

用法
----
    python cadview.py                  # 启动服务并打开浏览器
    python cadview.py model.step       # 启动并直接载入该文件
    python cadview.py --dir D:\\models # 指定起始目录
"""
from __future__ import annotations

__version__ = "1.0.0"

import argparse
import json
import os
import secrets
import socket
import struct
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from cadview_core import (
    export_stl,
    export_step,
    has_ocp,
    import_any,
    mesh_stats,
    rotate_mesh,
    to_numpy,
)
from winfiledlg import pick_file, pick_folder, pick_save

MESH_MAGIC = b"CMSH"
MESH_SUFFIXES = (".step", ".stp", ".stl", ".obj")
MAX_UPLOAD = 1 << 20


# --------------------------------------------------------------------------- #
# 资源定位（兼容 PyInstaller 打包后的临时目录）
# --------------------------------------------------------------------------- #
def web_root() -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "web")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


# --------------------------------------------------------------------------- #
# 会话状态
# --------------------------------------------------------------------------- #
class Session:
    """保存当前模型与其累积旋转。"""

    def __init__(self) -> None:
        self.path: Optional[str] = None
        self.mesh = None          # 当前（含旋转）
        self.original = None      # 导入时
        self.version = 0          # 每次变化 +1，用于前端缓存失效
        self.last_error: str = ""

    # -- 操作 ------------------------------------------------------------
    def open(self, path: str) -> dict:
        mesh = import_any(path)
        self.path = os.path.abspath(path)
        self.mesh = mesh
        self.original = mesh.copy()
        self.version += 1
        return self.state()

    def rotate(self, axis: str, deg: float) -> dict:
        if self.mesh is None:
            raise ValueError("尚未载入模型")
        self.mesh = rotate_mesh(self.mesh, axis, deg)
        self.version += 1
        return self.state()

    def reset(self) -> dict:
        if self.original is None:
            raise ValueError("尚未载入模型")
        self.mesh = self.original.copy()
        self.version += 1
        return self.state()

    def state(self) -> dict:
        if self.mesh is None:
            return {"loaded": False, "version": self.version, "ocp": has_ocp()}
        nv, nt, vol = mesh_stats(self.mesh)
        P, _ = to_numpy(self.mesh)
        lo = P.min(axis=0)
        hi = P.max(axis=0)
        return {
            "loaded": True,
            "version": self.version,
            "ocp": has_ocp(),
            "path": self.path,
            "name": os.path.basename(self.path) if self.path else "",
            "verts": nv,
            "tris": nt,
            "volume": vol,
            "bbox": {"min": lo.tolist(), "max": hi.tolist()},
            "size": [float(hi[i] - lo[i]) for i in range(3)],
        }


# --------------------------------------------------------------------------- #
# HTTP 处理
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = f"cadview/{__version__}"
    session: Session = Session()
    token: str = ""
    root: str = ""

    # -- 工具 ------------------------------------------------------------
    def log_message(self, fmt, *args):  # 静默默认日志
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json",
              extra: Optional[dict] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_UPLOAD:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _authorized(self, q: dict) -> bool:
        return q.get("t", [""])[0] == self.token

    # -- GET -------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        route = u.path

        if route in ("/", "/index.html"):
            return self._serve_file("index.html", "text/html; charset=utf-8")
        if route.startswith("/static/"):
            name = os.path.basename(unquote(route[len("/static/"):]))
            ctype = {".js": "text/javascript; charset=utf-8",
                     ".css": "text/css; charset=utf-8",
                     ".html": "text/html; charset=utf-8"}.get(
                         os.path.splitext(name)[1].lower(),
                         "application/octet-stream")
            return self._serve_file(name, ctype)

        if not self._authorized(q):
            return self._json({"error": "unauthorized"}, 403)

        if route == "/api/state":
            return self._json(self.session.state())
        if route == "/api/list":
            return self._list(q.get("dir", [""])[0])
        if route == "/api/mesh":
            return self._mesh()
        return self._json({"error": "not found"}, 404)

    # -- POST ------------------------------------------------------------
    def do_POST(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._authorized(q):
            return self._json({"error": "unauthorized"}, 403)
        route = u.path
        body = self._body()
        try:
            if route == "/api/pick-file":
                # 弹出 Windows 原生「打开文件」对话框（模态，阻塞本请求线程）
                init = str(body.get("dir") or "").strip()
                path = pick_file(title="选择要打开的模型文件", init_dir=init)
                return self._json({"picked": path or "", "canceled": not path})
            if route == "/api/pick-folder":
                init = str(body.get("dir") or "").strip()
                path = pick_folder(title="选择文件夹", init_dir=init)
                return self._json({"picked": path or "", "canceled": not path})
            if route == "/api/pick-save":
                init = str(body.get("dir") or "").strip()
                name = str(body.get("name") or "").strip()
                fmt = str(body.get("format") or "step").lower()
                filters = ([("STEP 文件", "*.step")] if fmt == "step"
                           else [("STL 文件", "*.stl")])
                filters.append(("所有文件", "*.*"))
                path = pick_save(title="导出模型", default_name=name,
                                 filters=filters, init_dir=init)
                return self._json({"picked": path or "", "canceled": not path})
            if route == "/api/open":
                path = (body.get("path") or "").strip()
                if not path:
                    raise ValueError("缺少文件路径")
                if not os.path.isfile(path):
                    raise ValueError(f"文件不存在：{path}")
                return self._json(self.session.open(path))
            if route == "/api/rotate":
                axis = str(body.get("axis", "")).lower()
                deg = float(body.get("deg", 0))
                if axis not in ("x", "y", "z"):
                    raise ValueError("axis 必须是 x / y / z")
                return self._json(self.session.rotate(axis, deg))
            if route == "/api/reset":
                return self._json(self.session.reset())
            if route == "/api/export":
                return self._export(body)
            if route == "/api/quit":
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
        except Exception as exc:  # noqa: BLE001
            return self._json({"error": str(exc)}, 400)
        return self._json({"error": "not found"}, 404)

    # -- 具体处理 --------------------------------------------------------
    def _serve_file(self, name: str, ctype: str) -> None:
        path = os.path.join(self.root, name)
        if not os.path.isfile(path):
            return self._json({"error": "not found"}, 404)
        with open(path, "rb") as f:
            data = f.read()
        self._send(200, data, ctype)

    def _list(self, raw: str):
        d = os.path.abspath(os.path.expanduser(raw or os.getcwd()))
        if not os.path.isdir(d):
            return self._json({"error": f"目录不存在：{d}"}, 400)
        dirs, files = [], []
        try:
            for name in sorted(os.listdir(d)):
                p = os.path.join(d, name)
                try:
                    if os.path.isdir(p):
                        dirs.append({"name": name, "path": p})
                    elif name.lower().endswith(MESH_SUFFIXES):
                        files.append({"name": name, "path": p,
                                      "size": os.path.getsize(p)})
                except OSError:
                    continue
        except PermissionError:
            return self._json({"error": f"无权限读取：{d}"}, 400)
        parent = os.path.dirname(d.rstrip("\\/")) or d
        return self._json({"dir": d, "parent": parent, "dirs": dirs, "files": files})

    def _mesh(self):
        if self.session.mesh is None:
            return self._json({"error": "尚未载入模型"}, 400)
        P, T = to_numpy(self.session.mesh)
        head = struct.pack("<4sII", MESH_MAGIC, len(P), len(T))
        body = head + P.astype("<f4").tobytes() + T.astype("<u4").tobytes()
        self._send(200, body, "application/octet-stream")

    def _export(self, body: dict):
        fmt = str(body.get("format", "stl")).lower()
        path = (body.get("path") or "").strip()
        if not path:
            raise ValueError("缺少导出路径")
        if self.session.mesh is None:
            raise ValueError("尚未载入模型")
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        fmt = ext or fmt
        if fmt == "stl":
            export_stl(self.session.mesh, path)
            method = "cutsim STL"
        elif fmt in ("step", "stp"):
            method = "cutsim 解析重建" if export_step(self.session.mesh, path) == "cutsim" \
                else "OCP 三角面"
        else:
            raise ValueError("仅支持导出 stl / step")
        return self._json({"ok": True, "path": os.path.abspath(path), "method": method,
                           "size": os.path.getsize(path)})


# --------------------------------------------------------------------------- #
# 启动
# --------------------------------------------------------------------------- #
def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def app_dir() -> str:
    """可写目录：打包后为 EXE 所在目录，否则为脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def log_path() -> str:
    return os.path.join(app_dir(), "cadview.log")


def show_message(text: str, title: str = "cadview") -> None:
    """在无法使用控制台时（如 windowed EXE）用系统弹窗提示。"""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    except Exception:
        pass


def append_log(lines) -> Optional[str]:
    """追加写入日志文件；返回路径，失败返回 None。"""
    try:
        path = log_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(str(x) for x in lines) + "\n")
        return path
    except Exception:
        return None


def redirect_stdio() -> None:
    """无控制台的 EXE 中 ``sys.stdout`` 为 None，``print`` 会抛异常。

    这里把标准输出/错误重定向到日志文件，保证后续任何 ``print`` 安全。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        fh = open(log_path(), "a", encoding="utf-8", buffering=1)
    except Exception:
        return

    class _Stream:
        def __init__(self, f):
            self._f = f

        def write(self, data):
            try:
                self._f.write(data)
            except Exception:
                pass

        def flush(self):
            try:
                self._f.flush()
            except Exception:
                pass

        def isatty(self):
            return False

    sys.stdout = _Stream(fh)
    sys.stderr = _Stream(fh)


def build_handler(token: str, root: str):
    class _H(Handler):
        pass

    _H.token = token
    _H.root = root
    _H.session = Session()
    return _H


def main(argv=None):
    redirect_stdio()
    ap = argparse.ArgumentParser(description="cadview · STEP/STL 查看与旋转（cutsim）")
    ap.add_argument("file", nargs="?", help="启动时直接载入的文件")
    ap.add_argument("--dir", default=None, help="文件浏览器的起始目录")
    ap.add_argument("--port", type=int, default=0, help="端口（0=随机）")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--file", dest="file_opt", default=None,
                    help="启动时直接载入的文件（与位置参数等价）")
    args = ap.parse_args(argv)

    target = args.file_opt or args.file
    root = web_root()
    if not os.path.isdir(root):
        print(f"错误：找不到前端资源目录 {root}", file=sys.stderr)
        show_message(f"找不到前端资源目录：\n{root}\n\n请确认安装包完整。", "cadview 启动失败")
        return 2

    token = secrets.token_urlsafe(16)
    port = args.port or find_free_port()
    handler = build_handler(token, root)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/?t={token}"

    start_dir = args.dir or (os.path.dirname(os.path.abspath(target)) if target else os.getcwd())
    print("=" * 62)
    print("  cadview · STEP/STL 查看 · 绕坐标轴旋转 · 导出")
    print(f"  服务地址   : {url}")
    print(f"  起始目录   : {start_dir}")
    print(f"  OpenCASCADE: {'可用（支持 STEP 导入/导出）' if has_ocp() else '不可用（仅 STL/OBJ）'}")
    print("  关闭页面左上角的「退出」按钮即可结束程序。")
    print("=" * 62, flush=True)

    if target and os.path.isfile(target):
        try:
            handler.session.open(target)
            print(f"  已载入     : {target}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  载入失败   : {exc}", flush=True)

    if not args.no_browser:
        def _open():
            try:
                ok = webbrowser.open(url)
            except Exception:
                ok = False
            if not ok:
                show_message(f"请在浏览器中打开下面的地址：\n\n{url}", "cadview")

        threading.Timer(0.6, _open).start()

    lines = [
        "=" * 62,
        "cadview - STEP/STL 查看 / 绕坐标轴旋转 / 导出",
        f"服务地址: {url}",
        f"起始目录: {start_dir}",
        f"OpenCASCADE: {'可用' if has_ocp() else '不可用（仅 STL/OBJ）'}",
        f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    log_file = append_log(lines)
    if log_file:
        print(f"  日志文件   : {log_file}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        httpd.server_close()
    return 0


def run_cli(argv=None) -> int:
    """带友好错误提示的入口：任何异常都写入日志并弹窗，不再抛原始 traceback。"""
    try:
        return main(argv)
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001
        tb = traceback.format_exc()
        path = append_log(["", "!!! 启动失败 !!!", tb])
        detail = f"\n\n详细错误已写入：\n{path}" if path else ""
        show_message(f"cadview 启动失败：\n\n{tb.splitlines()[-1]}{detail}", "cadview 启动失败")
        return 1


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
