"""cadview_core — STEP/STL 导入、绕坐标轴旋转、导出。

实现基于 cutsim：
  * STL / OBJ 导入、STL 导出：cutsim 的 ``TriMesh``（纯 Python，无外部依赖）
  * STEP 导出：优先用 cutsim 的 ``Engine.write_step_file``（内部做平面/圆柱面解析重建，
    对闭合流形网格会重建出干净 B-rep）；失败（非流形）时回退到 OCP 三角面 B-rep。
  * STEP 导入：目前没有纯 Python 的 STEP 读取器，必须用 OpenCASCADE（cadquery-ocp）。
    三角化后转成 cutsim ``TriMesh``，从而后续旋转/导出都走 cutsim。

旋转：直接对 ``TriMesh.positions`` 施加绕世界坐标轴的旋转矩阵（绕 X/Y/Z 累积），
三角索引不变。
"""

from __future__ import annotations

import os
from typing import Tuple

import numpy as np
from cutsim import Engine, EngineOptions, StockShape, TriMesh


# --------------------------------------------------------------------------- #
# STEP 导入（依赖 OCP / cadquery-ocp）
# --------------------------------------------------------------------------- #
def has_ocp() -> bool:
    """是否可用 OpenCASCADE（决定 STEP 导入与 STEP 导出的回退路径）。"""
    try:
        import OCP.STEPControl  # noqa: F401
        return True
    except Exception:
        return False


def import_step(path: str, deflection: float = 0.05, relative: bool = True) -> TriMesh:
    """用 OCP 读取 STEP，三角化后转成 cutsim TriMesh。

    ``deflection``：线性偏差（mm）。``relative=True`` 时相对模型尺寸。
    """
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRep import BRep_Tool
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    from OCP.TopLoc import TopLoc_Location

    reader = STEPControl_Reader()
    if reader.ReadFile(path) != IFSelect_RetDone:
        raise IOError(f"无法读取 STEP 文件：{path}")
    reader.TransferRoots()
    shape = reader.OneShape()

    BRepMesh_IncrementalMesh(shape, deflection, relative)

    mesh = TriMesh()
    base = 0
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face(explorer.Current())
        explorer.Next()
        loc = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face, loc)
        if poly is None:
            continue
        tr = loc.Transformation()
        n_nodes = poly.NbNodes()
        n_tris = poly.NbTriangles()
        for i in range(1, n_nodes + 1):
            p = poly.Node(i).Transformed(tr)
            mesh.positions.append((float(p.X()), float(p.Y()), float(p.Z())))
        for i in range(1, n_tris + 1):
            tri = poly.Triangle(i)
            a, b, c = tri.Get()
            mesh.triangles.append((base + a - 1, base + b - 1, base + c - 1))
        base = len(mesh.positions)
    if not mesh.triangles:
        raise IOError("STEP 文件三角化后没有三角形（可能是空几何或不含实体面）")
    return mesh


# --------------------------------------------------------------------------- #
# 统一导入入口（按扩展名分发）
# --------------------------------------------------------------------------- #
def import_any(path: str, deflection: float = 0.05) -> TriMesh:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext == "stl":
        return TriMesh.read_stl_file(path)
    if ext == "obj":
        return TriMesh.read_obj_file(path)
    if ext in ("step", "stp"):
        if not has_ocp():
            raise IOError("STEP 导入需要 OpenCASCADE（cadquery-ocp），当前环境未安装。")
        return import_step(path, deflection=deflection)
    raise IOError(f"不支持的导入格式：.{ext}（仅支持 stl / obj / step / stp）")


# --------------------------------------------------------------------------- #
# 旋转（绕世界坐标轴，累积）
# --------------------------------------------------------------------------- #
def rotation_matrix(axis: str, deg: float) -> np.ndarray:
    """绕世界坐标轴的标准旋转矩阵（右手定则，正角度为轴正向）。

    * 绕 X 轴：``Y → Z``，``Z → −Y``
    * 绕 Y 轴：``Z → X``，``X → −Z``
    * 绕 Z 轴：``X → Y``，``Y → −X``
    """
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    if axis == "x":
        return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])
    if axis == "y":
        return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    if axis == "z":
        return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    raise ValueError("axis 必须是 'x' / 'y' / 'z'")


def rotate_mesh(mesh: TriMesh, axis: str, deg: float) -> TriMesh:
    """返回绕指定世界坐标轴旋转 ``deg`` 度后的新网格（累积旋转请对当前网格再次调用）。"""
    if axis not in ("x", "y", "z"):
        raise ValueError("axis 必须是 'x' / 'y' / 'z'")
    R = rotation_matrix(axis, deg)
    P = np.asarray(mesh.positions, dtype=np.float64) @ R.T
    out = TriMesh()
    out.positions = [tuple(float(v) for v in row) for row in P]
    out.triangles = [tuple(t) for t in mesh.triangles]
    return out


# --------------------------------------------------------------------------- #
# 导出
# --------------------------------------------------------------------------- #
def export_stl(mesh: TriMesh, path: str) -> None:
    """用 cutsim 导出二进制 STL（水密、按三角面法向）。"""
    ensure_parent_dir(path)
    mesh.write_stl_file(path)


def ensure_parent_dir(path: str) -> None:
    """确保输出文件的父目录存在；不存在则创建。"""
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


def export_step(mesh: TriMesh, path: str, name: str = "part") -> str:
    """导出 STEP。优先 cutsim（解析重建），失败回退 OCP 三角面。

    返回实际使用的方法：``"cutsim"`` 或 ``"ocp"``。
    """
    ensure_parent_dir(path)
    try:
        return _export_step_cutsim(mesh, path, name)
    except Exception as exc:  # noqa: BLE001
        if not has_ocp():
            raise
        try:
            return _export_step_ocp(mesh, path)
        except Exception:  # noqa: BLE001
            raise RuntimeError(
                f"STEP 导出失败（cutsim: {exc}；OCP 回退同样失败）"
            ) from exc


def _export_step_cutsim(mesh: TriMesh, path: str, name: str) -> str:
    m = mesh.copy()
    if m.positions:
        m.merge_vertices(1e-3)
    eng = Engine([StockShape.mesh(m)], EngineOptions())
    eng.write_step_file(path, name)
    return "cutsim"


def _export_step_ocp(mesh: TriMesh, path: str) -> str:
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Shell
    from OCP.BRepBuilderAPI import (
        BRepBuilderAPI_MakePolygon,
        BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_Sewing,
        BRepBuilderAPI_MakeSolid,
    )
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCP.gp import gp_Pnt

    P = np.asarray(mesh.positions, dtype=np.float64)
    builder = BRep_Builder()
    shell = TopoDS_Shell()
    builder.MakeShell(shell)
    for a, b, c in mesh.triangles:
        poly = BRepBuilderAPI_MakePolygon()
        for idx in (a, b, c):
            x, y, z = P[idx]
            poly.Add(gp_Pnt(float(x), float(y), float(z)))
        poly.Close()
        builder.Add(shell, BRepBuilderAPI_MakeFace(poly.Wire()).Face())

    # 缝合 -> 修正朝向/连接 -> 尽量做成实体
    sew = BRepBuilderAPI_Sewing(1e-4)
    sew.Add(shell)
    sew.Perform()
    sewn = sew.SewedShape()
    try:
        sol_shape = BRepBuilderAPI_MakeSolid(TopoDS_Shell(sewn)).Solid()
        if sol_shape.IsNull():
            sol_shape = shell
    except Exception:
        sol_shape = shell

    from OCP.IFSelect import IFSelect_RetDone

    writer = STEPControl_Writer()
    writer.Transfer(sol_shape, STEPControl_AsIs)
    status = writer.Write(path)
    if status != IFSelect_RetDone:
        raise IOError(f"STEP 写入失败（状态码 {status}）")
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise IOError("STEP 写入失败（输出文件为空或未生成）")
    return "ocp"


# --------------------------------------------------------------------------- #
# 辅助：统计信息
# --------------------------------------------------------------------------- #
def mesh_stats(mesh: TriMesh) -> Tuple[int, int, float]:
    """返回 (顶点数, 三角形数, 体积mm³ 绝对值)。"""
    vol = abs(mesh.signed_volume()) if mesh.triangles else 0.0
    return len(mesh.positions), len(mesh.triangles), float(vol)


def to_numpy(mesh: TriMesh) -> Tuple[np.ndarray, np.ndarray]:
    """返回 (positions[N,3], triangles[M,3]) 的 numpy 数组，供可视化使用。"""
    P = np.asarray(mesh.positions, dtype=np.float64).reshape(-1, 3)
    T = np.asarray(mesh.triangles, dtype=np.int64).reshape(-1, 3)
    return P, T
