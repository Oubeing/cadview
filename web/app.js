import * as THREE from 'three';
import { OrbitControls } from '/static/OrbitControls.js';

// ---------------------------------------------------------------- 参数
const TOKEN = new URLSearchParams(location.search).get('t') || '';
const $ = (id) => document.getElementById(id);

const state = {
  version: -1,
  loaded: false,
  box: null,
  path: '',
  dir: '',
};

// ---------------------------------------------------------------- 场景
const canvas = $('canvas');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setClearColor(0xffffff, 1);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100000);
camera.up.set(0, 0, 1);
camera.position.set(60, -90, 55);

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.12;

scene.add(new THREE.HemisphereLight(0xffffff, 0xd8dee7, 1.15));
const key = new THREE.DirectionalLight(0xffffff, 0.85);
key.position.set(1, -1.2, 1.1);
scene.add(key);
const fill = new THREE.DirectionalLight(0xffffff, 0.3);
fill.position.set(-1, 0.8, -0.6);
scene.add(fill);

// 坐标轴：X 红 / Y 绿 / Z 蓝（Z 向上，与相机 up 一致）
// 坐标轴位于世界原点，表示模型的绝对方位（不随模型旋转而移动）
const axes = new THREE.AxesHelper(20);
scene.add(axes);

// 轴端文字标签（Sprite，始终朝向相机）
function makeAxisLabel(text, color) {
  const cv = document.createElement('canvas');
  cv.width = cv.height = 64;
  const ctx = cv.getContext('2d');
  ctx.fillStyle = color;
  ctx.font = 'bold 44px "Microsoft YaHei", "Segoe UI", sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 32, 34);
  const tex = new THREE.CanvasTexture(cv);
  tex.needsUpdate = true;
  const spr = new THREE.Sprite(new THREE.SpriteMaterial({
    map: tex, depthTest: false, transparent: true,
  }));
  spr.renderOrder = 999;
  return spr;
}

const axisLabels = new THREE.Group();
const labelX = makeAxisLabel('X', '#d64545');
const labelY = makeAxisLabel('Y', '#2f9e44');
const labelZ = makeAxisLabel('Z', '#2f6fd0');
axisLabels.add(labelX, labelY, labelZ);
scene.add(axisLabels);

const grid = new THREE.GridHelper(100, 20, 0x9aa6b6, 0xd8dee7);
grid.rotation.x = Math.PI / 2;      // Z-up
scene.add(grid);

const material = new THREE.MeshStandardMaterial({
  color: 0x4f9bd9, metalness: 0.15, roughness: 0.55,
  side: THREE.DoubleSide, flatShading: false,
});
let mesh = null;

// ---------------------------------------------------------------- 渲染循环
function resize() {
  const vp = $('viewport');
  const w = vp.clientWidth, h = vp.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
new ResizeObserver(resize).observe($('viewport'));

// 角落的坐标系方向指示器：把世界轴投影到屏幕，随相机实时转动
const axg = $('axg');
const AX_LEN = 34;

function updateAxisWidget() {
  // 相机朝向矩阵：把世界坐标方向变换到屏幕空间
  const m = new THREE.Matrix4().extractRotation(camera.matrixWorldInverse);
  const p = (v) => {
    const e = v.clone().applyMatrix4(m);
    return [50 + e.x * AX_LEN, 50 - e.y * AX_LEN, e.z];
  };
  const [x1, y1, xz] = p(new THREE.Vector3(1, 0, 0));
  const [y2, y2p, yz] = p(new THREE.Vector3(0, 1, 0));
  const [z2, z2p, zz] = p(new THREE.Vector3(0, 0, 1));

  // 指向观察者（z >= 0）的轴画实线，背向的画淡线
  const setAxis = (sel, x, y, front) => {
    const el = axg.querySelector(sel);
    if (!el) return;
    el.setAttribute('x2', x.toFixed(1));
    el.setAttribute('y2', y.toFixed(1));
    el.style.opacity = front ? '1' : '0.3';
  };
  setAxis('.ax-x', x1, y1, xz >= 0);
  setAxis('.ax-y', y2, y2p, yz >= 0);
  setAxis('.ax-z', z2, z2p, zz >= 0);

  // 标签跟随轴端点，并钳制在 100×100 视口内
  const putLabel = (sel, x, y, dx, dy) => {
    const el = axg.querySelector(sel);
    if (!el) return;
    const cx = Math.min(90, Math.max(10, x + dx));
    const cy = Math.min(93, Math.max(7, y + dy));
    el.setAttribute('x', cx.toFixed(1));
    el.setAttribute('y', cy.toFixed(1));
  };
  putLabel('.ax-tx', x1, y1, 0, -6);
  putLabel('.ax-ty', y2, y2p, 9, 4);
  putLabel('.ax-tz', z2, z2p, -9, 9);
}

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
  updateAxisWidget();
}
resize();
animate();

// ---------------------------------------------------------------- API
async function api(path, body) {
  const url = path + (path.includes('?') ? '&' : '?') + 't=' + encodeURIComponent(TOKEN);
  const opts = body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    : {};
  const res = await fetch(url, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
  return data;
}

function setMsg(text, cls) {
  const el = $('stat-msg');
  el.textContent = text || '';
  el.className = 'msg' + (cls ? ' ' + cls : '');
}

function fmtSize(n) {
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(1) + ' MB';
}

// ---------------------------------------------------------------- 载入网格
async function refreshMesh() {
  const res = await fetch('/api/mesh?t=' + encodeURIComponent(TOKEN) + '&v=' + state.version);
  if (!res.ok) return;
  const buf = await res.arrayBuffer();
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== 'CMSH') return;
  const nverts = dv.getUint32(4, true);
  const ntris = dv.getUint32(8, true);
  const pos = new Float32Array(buf, 12, nverts * 3);
  const idx = new Uint32Array(buf, 12 + nverts * 12, ntris * 3);

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setIndex(new THREE.BufferAttribute(idx, 1));
  geo.computeVertexNormals();
  geo.computeBoundingBox();
  geo.computeBoundingSphere();

  if (mesh) {
    mesh.geometry.dispose();
    mesh.geometry = geo;
  } else {
    mesh = new THREE.Mesh(geo, material);
    scene.add(mesh);
  }
  const bb = geo.boundingBox;
  state.box = bb;
  fitView();
}

function fitView() {
  if (!mesh || !state.box) return;
  const bb = state.box;
  const c = new THREE.Vector3();
  bb.getCenter(c);
  const s = new THREE.Vector3();
  bb.getSize(s);
  const radius = Math.max(s.length() / 2, 1e-3);
  const dist = radius / Math.sin((camera.fov * Math.PI) / 360) * 1.25;
  const dir = new THREE.Vector3(0.85, -1.0, 0.62).normalize();
  camera.position.copy(c).addScaledVector(dir, dist);
  camera.near = Math.max(radius / 1000, 0.01);
  camera.far = dist * 20 + radius * 10;
  camera.updateProjectionMatrix();
  controls.target.copy(c);
  controls.update();

  const g = grid;
  g.position.set(c.x, c.y, bb.min.z);
  const span = Math.max(s.x, s.y, s.z) || 20;
  g.scale.setScalar((span * 1.6) / 100);

  // 坐标轴固定在世界原点（不随模型旋转），长度取模型尺寸的 30%
  const axLen = span * 0.3;
  axes.scale.setScalar(axLen / 20);
  axes.position.set(0, 0, 0);
  axisLabels.position.set(0, 0, 0);
  const labScale = axLen * 0.12;
  labelX.position.set(axLen * 1.12, 0, 0);
  labelY.position.set(0, axLen * 1.12, 0);
  labelZ.position.set(0, 0, axLen * 1.12);
  for (const lb of [labelX, labelY, labelZ]) lb.scale.setScalar(labScale);
}

// ---------------------------------------------------------------- 状态刷新
async function refreshState() {
  const s = await api('/api/state');
  state.version = s.version;
  state.loaded = !!s.loaded;
  state.path = s.path || '';
  $('engine-badge').textContent = s.ocp ? 'cutsim + OpenCASCADE' : 'cutsim（无 STEP 导入）';
  if (s.loaded) {
    $('empty').classList.add('hidden');
    $('stat-name').textContent = s.name;
    $('stat-model').textContent =
      `顶点 ${s.verts.toLocaleString()} · 三角面 ${s.tris.toLocaleString()} · 体积 ${s.volume.toLocaleString(undefined, { maximumFractionDigits: 3 })} mm³`;
    const cf = $('current-file');
    cf.classList.remove('hidden');
    cf.querySelector('.cf-name').textContent = s.name;
    cf.querySelector('.cf-path').textContent = s.path;
    if (!$('export-path').value.trim()) {
      $('export-path').value = s.path.replace(/\.[^.]+$/, '') + '_rotated.' +
        ($('export-format').value === 'stl' ? 'stl' : 'step');
    }
  } else {
    $('empty').classList.remove('hidden');
    $('current-file').classList.add('hidden');
    $('stat-name').textContent = '未载入模型';
    $('stat-model').textContent = '';
  }
}

// ---------------------------------------------------------------- 操作
async function openModel(path) {
  setMsg('正在载入 …');
  $('loading').classList.remove('hidden');
  try {
    const s = await api('/api/open', { path });
    state.version = s.version;
    await refreshMesh();
    await refreshState();
    setMsg('已载入 ' + s.name, 'ok');
  } catch (e) {
    setMsg(String(e.message || e), 'err');
  } finally {
    $('loading').classList.add('hidden');
  }
}

// 弹出 Windows 原生「打开文件」对话框
async function pickFile() {
  $('loading').classList.remove('hidden');
  setMsg('请在弹出的对话框中选择文件…');
  try {
    const r = await api('/api/pick-file', { dir: state.dir });
    if (r.canceled) { setMsg('已取消'); return; }
    state.dir = r.picked.replace(/[\\/][^\\/]*$/, '');
    await openModel(r.picked);
    await listDir(state.dir);
  } catch (e) {
    setMsg(String(e.message || e), 'err');
  } finally {
    $('loading').classList.add('hidden');
  }
}

// 弹出 Windows 原生「浏览文件夹」对话框
async function pickDir() {
  $('loading').classList.remove('hidden');
  setMsg('请在弹出的对话框中选择文件夹…');
  try {
    const r = await api('/api/pick-folder', { dir: state.dir });
    if (r.canceled) { setMsg('已取消'); return; }
    state.dir = r.picked;
    await listDir(state.dir);
    setMsg('当前目录：' + r.picked, 'ok');
  } catch (e) {
    setMsg(String(e.message || e), 'err');
  } finally {
    $('loading').classList.add('hidden');
  }
}

// 弹出 Windows 原生「另存为」对话框
async function pickSave() {
  const fmt = $('export-format').value;
  const cur = $('export-path').value.trim();
  const name = cur ? cur.replace(/^.*[\\/]/, '') : ('model.' + fmt);
  const dir = cur ? cur.replace(/[\\/][^\\/]*$/, '') : state.dir;
  try {
    const r = await api('/api/pick-save', { dir: dir, name: name, format: fmt });
    if (r.canceled) { setMsg('已取消'); return; }
    $('export-path').value = r.picked;
    setMsg('已选择输出路径', 'ok');
  } catch (e) {
    setMsg(String(e.message || e), 'err');
  }
}

async function rotate(axis) {
  if (!state.loaded) { setMsg('请先载入模型', 'err'); return; }
  const deg = parseFloat($('angle').value);
  if (!isFinite(deg)) { setMsg('请输入有效角度', 'err'); return; }
  try {
    const s = await api('/api/rotate', { axis, deg });
    state.version = s.version;
    await refreshMesh();
    await refreshState();
    setMsg(`绕 ${axis.toUpperCase()} 轴旋转 ${deg}°`, 'ok');
  } catch (e) {
    setMsg(String(e.message || e), 'err');
  }
}

async function resetTransform() {
  if (!state.loaded) { setMsg('请先载入模型', 'err'); return; }
  try {
    const s = await api('/api/reset', {});
    state.version = s.version;
    await refreshMesh();
    await refreshState();
    setMsg('已复位变换', 'ok');
  } catch (e) {
    setMsg(String(e.message || e), 'err');
  }
}

async function exportModel() {
  if (!state.loaded) { setMsg('请先载入模型', 'err'); return; }
  let path = $('export-path').value.trim();
  if (!path) { setMsg('请先选择输出路径', 'err'); return; }
  const fmt = $('export-format').value;
  const ext = '.' + fmt;
  if (!path.toLowerCase().endsWith(ext)) path += ext;
  setMsg('正在导出 …');
  try {
    const r = await api('/api/export', { path, format: fmt });
    $('export-hint').textContent = `已导出：${r.path}（${r.method}，${fmtSize(r.size)}）`;
    setMsg('导出完成 → ' + r.path, 'ok');
  } catch (e) {
    setMsg(String(e.message || e), 'err');
  }
}

async function listDir(dir) {
  try {
    const r = await api('/api/list?dir=' + encodeURIComponent(dir || ''));
    state.dir = r.dir;
    const box = $('file-list');
    box.innerHTML = '';
    if (r.parent && r.parent !== r.dir) {
      const up = document.createElement('div');
      up.className = 'item dir';
      up.innerHTML = '<span>↑ 上级目录</span>';
      up.onclick = () => listDir(r.parent);
      box.appendChild(up);
    }
    r.dirs.forEach((d) => {
      const it = document.createElement('div');
      it.className = 'item dir';
      it.innerHTML = `<span>📁 ${esc(d.name)}</span>`;
      it.onclick = () => listDir(d.path);
      box.appendChild(it);
    });
    r.files.forEach((f) => {
      const it = document.createElement('div');
      it.className = 'item' + (f.path === state.path ? ' sel' : '');
      it.innerHTML = `<span>${esc(f.name)}</span><span class="sz">${fmtSize(f.size)}</span>`;
      it.onclick = () => openModel(f.path);
      box.appendChild(it);
    });
    if (!r.dirs.length && !r.files.length) {
      box.innerHTML = '<div class="muted small" style="padding:8px">该目录没有 STEP / STL 文件</div>';
    }
  } catch (e) {
    setMsg(String(e.message || e), 'err');
  }
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// ---------------------------------------------------------------- 事件绑定
$('btn-pick-file').onclick = pickFile;
$('btn-pick-dir').onclick = pickDir;
$('btn-pick-save').onclick = pickSave;

document.querySelectorAll('.rot-grid button').forEach((b) => {
  b.onclick = () => rotate(b.dataset.axis);
});
$('btn-reset').onclick = resetTransform;
$('btn-export').onclick = exportModel;
$('export-format').onchange = () => {
  if (!state.path) return;
  const base = state.path.replace(/\.[^.]+$/, '');
  $('export-path').value = base + '_rotated.' + $('export-format').value;
};
$('btn-fit').onclick = fitView;

$('opt-axes').onchange = (e) => {
  axes.visible = e.target.checked;
  axisLabels.visible = e.target.checked;
};
$('opt-grid').onchange = (e) => { grid.visible = e.target.checked; };
$('opt-wire').onchange = (e) => { material.wireframe = e.target.checked; };

$('btn-quit').onclick = async () => {
  try { await api('/api/quit', {}); } catch (e) { /* 服务已退出 */ }
  window.close();
};

// ---------------------------------------------------------------- 启动
(async function init() {
  await refreshState();
  if (state.loaded) await refreshMesh();
  const s = await api('/api/state');
  state.dir = s.path ? s.path.replace(/[\\/][^\\/]*$/, '') : '';
  await listDir(state.dir);
})();
