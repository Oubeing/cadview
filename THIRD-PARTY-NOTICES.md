# 第三方组件与许可声明

cadview 本体以 MIT 协议发布（见 [LICENSE](LICENSE)）。项目在运行时依赖、并在打包产物
（`cadview-win64.zip` / `cadview.exe`）中随包分发下列第三方组件。各组件的著作权与许可
归其各自作者所有，清单如下。

## 运行时依赖

| 组件 | 许可 | 用途 | 上游 |
|---|---|---|---|
| [cutsim](https://github.com/Oubeing/cutsim-0.1.0) | Apache-2.0 | 三角网格容器、STL 读写、STEP 解析重建 | Oubeing/cutsim-0.1.0 |
| [manifold3d](https://github.com/elalish/manifold) | Apache-2.0 | cutsim 的网格布尔运算后端 | elalish/manifold |
| [cadquery-ocp](https://github.com/CadQuery/OCP) | LGPL-2.1（含 OCCT 例外条款） | STEP 导入三角化、STEP 导出回退（OpenCASCADE 绑定） | CadQuery/OCP |
| [NumPy](https://numpy.org/) | BSD-3-Clause | 网格顶点/三角面的数值运算 | numpy/numpy |
| [VTK](https://vtk.org/) | BSD-3-Clause | 由 OCP 间接引入的运行时库 | Kitware/VTK |
| [three.js](https://threejs.org/) | MIT | 前端三维渲染（`web/three.module.js`） | mrdoob/three.js |
| [OrbitControls](https://threejs.org/docs/#examples/en/controls/OrbitControls) | MIT | 相机轨道控制（`web/OrbitControls.js`） | mrdoob/three.js |

## 打包产物额外包含

PyInstaller 生成的 `cadview-win64.zip` 还会内嵌 Python 解释器（PSF License）以及
Microsoft Visual C++ 运行时（`VCRUNTIME140.dll`、`msvcp140.dll`、`ucrtbase.dll` 等，
随 Windows 分发）。这些组件的许可由各自提供方规定。

## Apache-2.0 组件的注意事项

cutsim 与 manifold3d 均为 Apache-2.0。再分发包含它们的二进制时，依据 Apache-2.0
第 4 条，需要：

1. 随分发提供 Apache-2.0 许可副本（https://www.apache.org/licenses/LICENSE-2.0）；
2. 保留原项目的版权、专利、商标与归属声明；
3. 若原项目附带 `NOTICE` 文件，需一并保留（cutsim 仓库根目录有 `NOTICE`）。

## LGPL 组件的注意事项

`cadquery-ocp` 以 LGPL-2.1（含 OpenCASCADE 例外）分发。以动态链接方式随包分发时，
需保留其许可声明并提供获取对应源码的途径；若要修改 OpenCASCADE 自身代码，修改部分
需按 LGPL 开放。

---

本清单依据打包目录 `_internal/` 中实际存在的组件整理。若后续升级依赖版本，请同步核对
并更新此文件。各组件许可全文以对应上游仓库为准。
