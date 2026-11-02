# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本：把 cadview 打包成单文件夹 EXE。

用法：
    pyinstaller cadview.spec --noconfirm
生成 dist/cadview/cadview.exe

要点
----
1. web/ 目录（HTML/CSS/JS + 内置 three.js）必须作为数据文件收进去，
   程序通过 sys._MEIPASS 定位，保证 EXE 离线也能显示三维视图。
2. OpenCASCADE（OCP）没有官方 PyInstaller hook，且子模块是动态导入的，
   必须用 collect_all 收全，否则 STEP 导入/导出会报“找不到 OCP.* 模块”。
3. cutsim 是纯 Python，manifold3d 是编译扩展，交给 PyInstaller 自动收集即可
   （collect_all 更保险）。
4. winfiledlg 只用 ctypes 调 Win32 API，无第三方依赖，但需显式列入 hiddenimports，
   否则 PyInstaller 可能因静态分析不到而漏收（cadview.py 顶层是 `from winfiledlg import ...`，
   通常能自动发现，显式列出更保险）。
"""
import PyInstaller.utils.hooks as hooks  # noqa: E402
from PyInstaller.building.utils import format_binaries_and_datas  # noqa: E402

block_cipher = None

hiddenimports = [
    "cadview_core",
    "winfiledlg",
    "cutsim",
    "cutsim.engine", "cutsim.mesh", "cutsim.tool", "cutsim.sweep",
    "cutsim.motion", "cutsim.stock", "cutsim.brep", "cutsim.geometry",
    "cutsim.kernel", "cutsim.kernel.manifold",
    "manifold3d",
    "numpy",
    "OCP",
    "OCP.STEPControl", "OCP.IFSelect", "OCP.BRepMesh", "OCP.BRep",
    "OCP.TopExp", "OCP.TopAbs", "OCP.TopoDS", "OCP.TopLoc",
    "OCP.GProp", "OCP.BRepGProp", "OCP.gp", "OCP.BRepBuilderAPI",
]

a = Analysis(
    ["cadview.py"],
    pathex=["."],
    binaries=[],
    datas=[("web", "web")],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 与本工具无关的重型依赖，去掉可显著减小体积
        "matplotlib", "trimesh", "shapely", "scipy", "networkx", "rtree",
        "pandas", "IPython", "notebook", "PIL", "PyQt5", "PySide2", "PySide6",
        "PyQt6", "vtk", "pyvista", "pyvistaqt", "pytest",
    ],
    noarchive=False,
)

for pkg in ["OCP", "manifold3d", "cutsim"]:
    try:
        datas, binaries, hidden = hooks.collect_all(pkg)
        # collect_all 返回的是 hook 风格 (源, 目标目录) 二元组，
        # 而 Analysis.datas / .binaries 需要 TOC 风格 (目标, 源, 类型) 三元组。
        for dest, src in format_binaries_and_datas(datas):
            a.datas.append((dest, src, "DATA"))
        for dest, src in format_binaries_and_datas(binaries):
            a.binaries.append((dest, src, "BINARY"))
        a.hiddenimports += hidden
    except Exception as exc:  # noqa: BLE001
        print("collect_all(%s) 跳过: %s" % (pkg, exc))

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cadview",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,      # 无控制台窗口
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="cadview",
)
