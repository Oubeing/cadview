# cadview — STEP / STL 查看 · 绕坐标轴旋转 · 导出

基于 **cutsim** 的桌面工具：导入 STEP / STL / OBJ，三维可视化，绕世界坐标轴
（X / Y / Z）任意旋转，再导出为 STEP 或 STL。打包为单个 EXE，双击即用。

```
dist\cadview\cadview.exe          # 双击运行，自动打开浏览器界面
dist\cadview\cadview.exe a.step   # 或直接载入某个文件
```

## 功能

- **导入**：STEP（`*.step` / `*.stp`）、STL（`*.stl`）、OBJ（`*.obj`）
- **可视化**：交互式三维视图，鼠标左键拖动旋转 / 滚轮缩放 / 右键平移，可切换坐标轴、网格、线框
- **原生文件对话框**：点「选择文件…」直接弹出 **Windows 原生打开对话框**，
  点「浏览文件夹…」弹出**原生文件夹浏览对话框**，点「另存为…」弹出**原生保存对话框**——
  无需手工输入路径
- **旋转**：绕 X / Y / Z 三个世界坐标轴旋转，**角度带正负号表示方向**
  （`+90°` 沿轴正向按右手定则，`−90°` 反向），可连续叠加；
  「复位（回到原始姿态）」一键还原
- **坐标系标注**：视图内固定绘制 **X（红）/ Y（绿）/ Z（蓝）** 世界坐标轴并带轴端文字标签，
  右上角有随相机转动的**坐标系方向指示器**（箭头指向各轴正向）
- **导出**：STL（二进制，cutsim 原生）、STEP（cutsim 优先，失败回退 OCP）
- 状态栏实时显示顶点数 / 三角面数 / 体积；左侧可浏览目录并直接点选模型
- 界面走本地 HTTP 服务 + 内置 three.js，**完全离线可用**，不依赖任何 CDN

## 界面结构

左侧为操作面板，右侧为三维视图：

| 区域 | 说明 |
|---|---|
| 打开模型 | 「选择文件…」弹原生打开对话框；「浏览文件夹…」弹原生文件夹对话框切换浏览目录；文件列表点选即载入 |
| 绕坐标轴旋转 | 角度输入框（可填负数）+ `X 轴 / Y 轴 / Z 轴` 三个按钮；「复位（回到原始姿态）」撤销所有旋转 |
| 导出 | 选格式（STL / STEP）+「另存为…」弹原生保存对话框，点「导出」，完成后显示实际写入方式与文件大小 |
| 显示 | 坐标轴 / 网格 / 线框开关；「适配视图」重新居中缩放 |

坐标系轴固定在**世界原点**，不随模型旋转而移动——因此可以直观看出模型相对世界坐标系的方位。

快捷键：`O` 打开、`F` 适配视图。右上角「退出」结束程序。

## cutsim 在其中扮演的角色

cutsim 是这套工具的核心几何容器（`TriMesh`）：

| 操作 | 实现 | 依赖 |
|---|---|---|
| STL / OBJ 导入 | `TriMesh.read_stl_file` / `read_obj_file` | cutsim（纯 Python） |
| 旋转 | 对 `TriMesh.positions` 施加绕轴旋转矩阵 | numpy |
| STL 导出 | `TriMesh.write_stl_file` | cutsim（纯 Python） |
| STEP 导出 | `Engine([StockShape.mesh(...)]) + write_step_file` | cutsim（解析重建平面/圆柱面） |
| STEP 导入 | OpenCASCADE 三角化 → `TriMesh` | OCP（cadquery-ocp） |
| STEP 导出回退 | 三角面 B-rep 写入 | OCP（仅当 cutsim 重建失败，如非流形网格） |

> **为什么 STEP 导入离不开 OCP？** 目前没有纯 Python 的 STEP 解析器，
> 必须借助 OpenCASCADE 把 B-rep 三角化后才能交给 cutsim 的网格表示。
> 而 STEP **导出** 的「解析重建」路径是 cutsim 自己用纯 Python 拼 STEP 实体，
> 不依赖 OCP（仅当网格不是闭合流形时回退到 OCP 三角面）。
>
> 因此：**没有 OCP 时，工具仍可正常导入 STL/OBJ、旋转、导出 STL 与 STEP
> （走 OCP 回退路径）；仅 STEP 导入不可用**，界面右上角徽标会显示
> 「cutsim（无 STEP 导入）」。

### 导出质量实测

以 Ø20×125 的螺旋槽工件为例（25170 顶点 / 8390 三角面 / 体积 35546.1191 mm³）：

- **STL**：导出后重新导入，体积 35546.11920 mm³（float32 存储误差，5e-7 相对量级）
- **STEP**（cutsim 解析重建，8.3 MB）：用 OpenCASCADE 回读 →
  **1 个实体 / 1 个闭合壳 / 7793 个面，体积 35546.1192 mm³，与网格体积误差 0.000%**，
  `BRepCheck` 有效，可直接进 CAE 划网格

## 常见问题

| 现象 | 原因与处理 |
|---|---|
| 双击 EXE 弹出 `Unhandled exception in script` | 早期版本漏了 `import socket`（`find_free_port()` 用到），现已修复。当前版本若再报错，会弹出中文提示框，完整 traceback 写入 **EXE 同目录的 `cadview.log`** |
| 导出报 `No such file or directory` | 旧版要求输出目录必须预先存在，现在会自动创建多级目录 |
| 导出报 `STEP 写入失败` | 输出路径不可写（磁盘满 / 无权限 / 路径含非法字符）。错误信息现在会同时给出 cutsim 与 OCP 两条路径的原因 |
| 页面空白、控制台无输出 | 无控制台 EXE 的 stdout 已重定向到 `cadview.log`，浏览器控制台另看 F12 |
| 点了「选择文件…」但对话框没出现 | 原生对话框是**模态**的，会阻塞该次请求直到你选完或取消。切到别的窗口时对话框可能在后台，可从任务栏切回。旧版「浏览」按钮无效的问题已改为原生文件夹对话框 |
| 文件夹对话框打开的位置不对 | 会通过 `BFFM_INITIALIZED` 回调自动定位到当前目录；若路径不存在则回退到用户主目录 |

日志文件位置：与 `cadview.exe` 同目录的 `cadview.log`（每次启动追加一段，便于回溯多次运行）。

## 目录结构

- `cadview.py` — 主程序：本地 HTTP 服务 + API + 浏览器启动
- `cadview_core.py` — 几何核心：导入 / 旋转 / 导出（全部基于 cutsim）
- `winfiledlg.py` — Windows 原生文件 / 文件夹 / 保存对话框（纯 ctypes，无额外依赖）
- `web/` — 前端资源（HTML / CSS / JS + 内置 three.js）
- `cadview.spec` — PyInstaller 打包脚本
- `README.md` — 本文档

## 从源码运行 / 重新打包

```bash
pip install manifold3d numpy          # cutsim 本体（pip install -e <cutsim 路径>）
pip install cadquery-ocp              # 可选：STEP 导入 / 导出的 OCP 回退
pip install pyinstaller

python cadview.py                     # 开发运行
pyinstaller cadview.spec --noconfirm  # 重新打包 -> dist\cadview\cadview.exe
```

命令行参数：`--dir <起始目录>`、`--port <端口>`、`--no-browser`（不自动开浏览器）、
`<文件>` 直接载入。

## 已知限制

- 导入的 STEP 会被**三角化**成网格，导出 STEP 时走「解析重建」——cutsim 只重建平面 / 圆柱面，
  其余为共面三角面合并。需要精确解析曲面时，请保留原始 STEP 作为主数据。
- 旋转是对当前网格的几何变换（累积），不做参数化历史。
- 服务只监听 `127.0.0.1`，并带一次性 token，避免同机其它进程误调。
- 打包体积较大（数百 MB），主要来自 OpenCASCADE 运行时，属正常现象。

## 下载

Windows 64 位免安装版见 [Releases](../../releases) 页面，下载 `cadview-win64.zip` 解压后双击
`cadview\cadview.exe` 即可，无需 Python 环境。

## 版本

当前版本 **1.0.0**。版本号定义在 `cadview.py` 的 `__version__`，同时作为 HTTP 响应的
`Server` 标识。

## 许可

本项目采用 [MIT License](LICENSE) 协议，Copyright (c) 2026 Oubeing。

本项目以依赖方式使用 [cutsim](https://github.com/Oubeing/cutsim-0.1.0)（Apache-2.0）
等第三方组件；打包后的 EXE 会随包分发这些组件，再分发时请一并保留
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) 中的许可声明与链接。
