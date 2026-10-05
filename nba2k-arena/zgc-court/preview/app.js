import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createTextureSafeLoader, inspectGroundTextures, prepareTextureGPU } from './texture-pipeline.js';

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const viewport = $('#viewport');
const preferencesKey = 'zgc-court-preview-v1';
let saved = {};
try { saved = JSON.parse(localStorage.getItem(preferencesKey) || '{}'); } catch {}
const layerState = { reference_half: true, open_half: true, fence: true, background: true, gameplay_anchors: false, ...(saved.layers || {}) };
const categoryState = { ground: true, hoops: true, ...(saved.categories || {}) };
let wireframe = saved.wireframe || false;
let currentView = saved.view || 'overview';
let model = null;
let displayedManifest = null;
let latestStatus = null;
let previewMode = 'game';
let nativeStatus = null;
let loadGeneration = 0;
let loadingBuildId = null;
let references = [];
let referenceIndex = 0;
let referenceSign = -1;
let cameraWorldYaw = 0;
let chilisViews = {};
let persistTimer;
let renderer;
let textureState = { phase: 'loading', message: '地面贴图：等待检查' };
let textureReport = null;
const imagePolicyErrors = [];
const scene = new THREE.Scene();
scene.background = new THREE.Color('#bec7b2');
const perspective = new THREE.PerspectiveCamera(43, 1, 0.05, 600);
const orthographic = new THREE.OrthographicCamera(-23, 23, 23, -23, 0.05, 600);
let camera = perspective;
let controls;
const names = { overview: '全景', top: '俯视 · Chili’s 在上方', bench: '右侧替补席 · 44 个独立位置', left_shop: '左侧门店 · 泥靴', skyline: '周边楼群 · 距离推定', skyline_left: '场内看左侧远楼', skyline_open: '场内看开放端远楼', chilis_plan: '矩形门店俯视', basket: '篮架正面', basket_side: '篮架侧面', basket_back: '篮架背面', fence_sign: '围网 A 牌 · 灯带尚未点亮', tall_lamp: '左侧高路灯 · 尚未点亮', open_floor: '另一半场 · 灰水泥与白线', chilis: 'Chili’s 主入口', chilis_terrace: '喷泉露台 · 主入口左侧绕角', chilis_walk: '店侧通道', chilis_detail: '露台细节', sideline: '侧线', open: '面向开放端', garden: '开放侧花园', ground: '地面近看' };
Object.assign(names, { chilis_sign: '主入口灯牌 · 未点亮', chilis_hardware: '门框与金属五金', chilis_canopy: '布雨棚与支架', chilis_paving: '门前灰石铺装' });
const ambient = new THREE.HemisphereLight(0xf6f7e9, 0x788660, 2.05);
scene.add(ambient);
const sun = new THREE.DirectionalLight(0xfff1ce, 2.7);
sun.position.set(-12, 35, 22);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.camera.left = -34;
sun.shadow.camera.right = 34;
sun.shadow.camera.top = 34;
sun.shadow.camera.bottom = -34;
sun.shadow.camera.near = 1;
sun.shadow.camera.far = 120;
sun.shadow.normalBias = 0.025;
sun.shadow.bias = -0.00006;
scene.add(sun);

function failCanvas(error) {
  $('#canvas-error').hidden = false;
  $('#canvas-error').textContent = `三维预览无法启动：${error.message}。请使用支持 WebGL 2 的浏览器，并开启硬件加速。`;
  $('#empty-state').hidden = true;
  showTextureState('failed', error.message);
  reportTextureRuntime('failed', { error: error.message });
}

function showTextureState(phase = textureState.phase, message = textureState.message) {
  textureState = { phase, message };
  const label = $('#texture-status');
  if (!label) return;
  label.dataset.state = phase;
  label.textContent = phase === 'ready' && !categoryState.ground ? '地面图层已隐藏，可在下方重新勾选。' : message;
}

function reportTextureRuntime(phase, detail = {}) {
  const report = { schema_version: 1, browser_side: true, pipeline: 'same-origin-preview-images-v2', phase, reported_at: new Date().toISOString(), build_id: textureReport?.build_id || displayedManifest?.build_id || null, max_texture_size: renderer?.capabilities.maxTextureSize || null, ground_layer_visible: categoryState.ground, image_policy_errors: imagePolicyErrors.slice(-4), ...textureReport, ...detail };
  // Full IFF material diagnostics exceed the browser's 64 KiB keepalive quota.
  fetch('/api/preview-diagnostics', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(report) }).catch(() => {});
}

document.addEventListener('securitypolicyviolation', event => {
  if (event.effectiveDirective === 'img-src' || event.effectiveDirective === 'connect-src') imagePolicyErrors.push({ directive: event.effectiveDirective, blocked_uri: event.blockedURI });
});

function persist() {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    if (!controls) return;
    try {
      localStorage.setItem(preferencesKey, JSON.stringify({
        layers: layerState, categories: categoryState, wireframe, view: currentView,
        camera: { type: camera.isOrthographicCamera ? 'orthographic' : 'perspective', position: camera.position.toArray(), up: camera.up.toArray(), target: controls.target.toArray(), zoom: camera.zoom, fov: camera.fov, maxDistance: controls.maxDistance, maxPolarAngle: controls.maxPolarAngle, game_world_yaw_degrees: cameraWorldYaw },
      }));
    } catch {}
  }, 250);
}

function makeControls(target = new THREE.Vector3(), options = {}) {
  controls?.dispose();
  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(target);
  controls.enableDamping = true;
  controls.dampingFactor = 0.075;
  controls.minDistance = 0.35;
  controls.maxDistance = options.maxDistance || 180;
  controls.minZoom = 0.35;
  controls.maxZoom = 30;
  controls.maxPolarAngle = camera.isOrthographicCamera ? Math.PI : (options.maxPolarAngle || Math.PI * 0.49);
  controls.enableRotate = !camera.isOrthographicCamera;
  controls.addEventListener('end', persist);
  controls.update();
}

function resize() {
  if (!renderer) return;
  const { width, height } = viewport.getBoundingClientRect();
  if (!width || !height) return;
  perspective.aspect = width / height;
  perspective.updateProjectionMatrix();
  const span = 20;
  orthographic.left = -span * width / height;
  orthographic.right = span * width / height;
  orthographic.top = span;
  orthographic.bottom = -span;
  orthographic.updateProjectionMatrix();
  renderer.setSize(width, height);
}

function markView() {
  $$('[data-view]').forEach(button => button.classList.toggle('active', button.dataset.view === currentView));
  $('#view-name').textContent = names[currentView] || '自由视角';
  $('#view-evidence-note').hidden = !currentView.startsWith('skyline');
}

function manifestWorldYaw(manifest = displayedManifest) {
  return manifest?.kind === 'native_iff' && manifest.game_world_yaw_degrees === 180 ? 180 : 0;
}

function alignCameraWorld(yaw) {
  if (cameraWorldYaw !== yaw && controls) {
    // The IFF decoder already rotates geometry. Move only the viewing frame.
    for (const vector of [camera.position, camera.up, controls.target]) {
      vector.x *= -1;
      vector.z *= -1;
    }
    controls.update();
  }
  cameraWorldYaw = yaw;
}

function chooseView(view, save = true) {
  if (!renderer) return;
  currentView = view;
  const s = referenceSign;
  const presets = {
    overview: { position: [-s * 31, 25, 32], target: [-s * 2, 0, -1] },
    top: { position: [0, 52, 0.001], target: [0, 0, 0] },
    basket: { position: [s * 8.8, 3.25, 0.2], target: [s * 13.12, 3.15, 0] },
    basket_side: { position: [s * 13.4, 3.75, 5.0], target: [s * 13.9, 2.9, 0] },
    basket_back: { position: [s * 17.4, 4.4, -3.4], target: [s * 13.55, 3.18, 0] },
    fence_sign: { position: [s * 7.5, 2.5, 6.1], target: [s * 9.5, 2.03, 9.123] },
    tall_lamp: { position: [-s * 7, 9.2, 20], target: [s * 4.2, 5.4, 9.85] },
    open_floor: { position: [-s * 3, 12, 8], target: [-s * 10.5, .01, 0] },
    chilis: { position: [s * 4, 2.05, 6.8], target: [s * 23, 3, -0.8] },
    sideline: { position: [s * 2, 6.0, 24], target: [s * 2, 1.5, 0] },
    open: { position: [s * 10, 4.5, 5], target: [-s * 12, 1.5, 0] },
    garden: { position: [-s * 12, 4.7, 9], target: [-s * 25, 2.8, -8.5] },
    ground: { position: [s * 3, 11, 9], target: [s * 8.7, 0.01, 0] },
    ...chilisViews,
    chilis_sign: { position: [-17.953, 3.80, 4.2], target: [-20.869, 3.80, 4.2], fov: 55 },
    chilis_hardware: { position: [-18.253, 1.62, 2.95], target: [-20.933, 1.55, 3.77], fov: 42 },
    chilis_canopy: { position: [-18.653, 1.75, 8.7], target: [-20.353, 2.75, 4.2], fov: 65 },
    chilis_paving: { position: [-17.953, 2.1, 6.4], target: [-20.303, .04, 5.0], fov: 53 },
  };
  const preset = presets[view] || presets.overview;
  camera = view === 'top' || preset.projection === 'orthographic' ? orthographic : perspective;
  // Keep both entrance columns and the side lettering visible from the narrow walk.
  perspective.fov = view === 'chilis' ? 90 : (preset.fov || 43);
  camera.up.set(0, 1, 0);
  if (view === 'top') camera.up.set(referenceSign, 0, 0);
  if (preset.up) camera.up.fromArray(preset.up);
  camera.position.fromArray(preset.position);
  camera.zoom = preset.zoom || 1;
  camera.updateProjectionMatrix();
  makeControls(new THREE.Vector3(...preset.target), preset);
  cameraWorldYaw = 0;
  alignCameraWorld(manifestWorldYaw());
  resize();
  markView();
  const referenceForView = { chilis: 40, chilis_sign: 40, chilis_hardware: 40, chilis_canopy: 47, chilis_paving: 40, chilis_terrace: 39, chilis_walk: 46, chilis_detail: 44, left_shop: 57, skyline: 61, skyline_left: 58, skyline_open: 64, chilis_plan: 66 };
  if (save && Number.isInteger(referenceForView[view]) && references.length > referenceForView[view]) showReference(referenceForView[view]);
  if (save) persist();
}

try {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  viewport.appendChild(renderer.domElement);
  renderer.domElement.setAttribute('aria-label', '中关村大融城球场，可拖动旋转、滚轮缩放、右键平移');
  chooseView(currentView, false);
  if (saved.camera?.position?.length === 3 && saved.camera?.target?.length === 3) {
    camera = saved.camera.type === 'orthographic' ? orthographic : perspective;
    camera.position.fromArray(saved.camera.position);
    camera.up.fromArray(saved.camera.up || [0, 1, 0]);
    camera.zoom = Math.max(0.35, Math.min(30, Number(saved.camera.zoom) || 1));
    if (camera.isPerspectiveCamera && Number.isFinite(saved.camera.fov)) camera.fov = saved.camera.fov;
    makeControls(new THREE.Vector3(...saved.camera.target), {
      maxDistance: Math.min(450, Math.max(180, Number(saved.camera.maxDistance) || 180)),
      maxPolarAngle: Math.min(Math.PI, Math.max(Math.PI * .49, Number(saved.camera.maxPolarAngle) || 0)),
    });
    cameraWorldYaw = saved.camera.game_world_yaw_degrees === 180 ? 180 : 0;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(viewport);
  resize();
  renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
  renderer.domElement.addEventListener('webglcontextlost', event => { event.preventDefault(); failCanvas(new Error('显卡绘图上下文已丢失，请刷新页面')); reportTextureRuntime('context_lost'); });
} catch (error) { failCanvas(error); }

function tagsFor(node) {
  const tags = [];
  for (let ancestor = node; ancestor; ancestor = ancestor.parent) {
    for (const value of [ancestor.name, ancestor.userData?.layer, ancestor.userData?.collection, ancestor.userData?.category]) {
      if (typeof value === 'string') tags.push(value.toLowerCase());
      if (Array.isArray(value)) tags.push(...value.map(String).map(value => value.toLowerCase()));
    }
  }
  return tags;
}

function applyLayers(root = model) {
  root?.traverse(node => {
    if (!node.isMesh && !node.isLine && !node.isPoints) return;
    const tags = tagsFor(node);
    const ground = tags.some(tag => /^(ground|floor|court_surface|court_art|artwork)(_|\.|$)/.test(tag) || tag === 'ground');
    let visible = true;
    for (const [layer, enabled] of Object.entries(layerState)) {
      if (ground && ['reference_half', 'open_half'].includes(layer)) continue;
      if (!enabled && tags.some(tag => tag === layer || tag.startsWith(layer + '_') || tag.startsWith(layer + '.'))) visible = false;
    }
    if (tags.some(tag => tag === 'preview_helpers' || tag.startsWith('preview_helpers_'))) visible = false;
    const hoops = tags.some(tag => /^(hoop|hoops|basket|backboard|rim|net|support)(_|\.|$)/.test(tag) || tag === 'hoops');
    if (ground && !categoryState.ground) visible = false;
    if (hoops && !categoryState.hoops) visible = false;
    node.visible = visible;
    if (node.isMesh) {
      const materials = Array.isArray(node.material) ? node.material : [node.material];
      for (const material of materials) if (material && 'wireframe' in material) material.wireframe = wireframe;
    }
  });
}

function disposeModel(root) {
  if (!root) return;
  const geometries = new Set();
  const materials = new Set();
  const textures = new Set();
  const images = new Set();
  root.traverse(node => {
    if (node.geometry) geometries.add(node.geometry);
    for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
      if (!material) continue;
      materials.add(material);
      for (const value of Object.values(material)) if (value?.isTexture) textures.add(value);
    }
    if (node.skeleton?.boneTexture) textures.add(node.skeleton.boneTexture);
  });
  geometries.forEach(geometry => geometry.dispose());
  textures.forEach(texture => {
    const data = texture.source?.data;
    for (const item of Array.isArray(data) ? data : [data]) if (item?.close) images.add(item);
    texture.dispose();
  });
  images.forEach(item => item.close());
  materials.forEach(material => material.dispose());
}

function setBuildState(title, description, phase = 'ready', error = null) {
  $('#status-title').textContent = title;
  $('#status-description').textContent = description;
  $('#build-state').dataset.state = phase;
  $('#error-details').hidden = !error;
  $('#error-text').textContent = error || '';
  if (!model) {
    $('#empty-state').classList.toggle('failed', phase === 'failed');
    $('#empty-state strong').textContent = title;
    $('#empty-state p').textContent = description;
  }
}

function updateVersions(status) {
  const manifest = status?.manifest;
  $('#source-version').textContent = status?.source_version || manifest?.source_version || '等待源文件';
  $('#preview-version').textContent = displayedManifest?.preview_version || '未显示';
  $('#iff-version').textContent = nativeStatus?.manifest?.iff_version || manifest?.iff_version || '未生成';
  const verified = nativeStatus?.manifest?.game_verified_version || manifest?.game_verified_version;
  $('#game-version').textContent = ['R11-context-defects','R11-gameplay-visible-with-seating-and-context-defects'].includes(verified) ? '上次打球可见 · 本轮席位待确认' : verified === 'R09-replay-defects' ? 'R09 打球正常 · 回放篮板异常' : verified === 'R08-replay-defects' ? 'R08 可见 · 回放篮板异常' : verified === 'R07-visible-with-defects' ? 'R07 可见 · 标记有遮挡' : verified === 'R06-visible' ? 'R06 画面已确认' : (verified || '尚未确认');
  $('#build-id').textContent = displayedManifest ? `${displayedManifest.kind === 'native_iff' ? '交付 IFF' : '编辑源'} · ${displayedManifest.preview_version || displayedManifest.build_id}` : '等待完整预览';
}

function describeNativeState() {
  if (previewMode !== 'game') return;
  if (!nativeStatus?.manifest) {
    setBuildState('游戏包预览准备中', '完成 IFF 后，将从包内模型与贴图生成预览。', 'building');
  } else if (nativeStatus.phase === 'stale') {
    setBuildState('游戏包已更新', '正在等待新包预览，当前画面仍是上一份交付文件。', 'building');
  } else if (loadingBuildId) {
    setBuildState('正在读取游戏包', '载入包内几何与贴图，完成后自动切换。', 'building');
  } else if (displayedManifest?.kind === 'native_iff' && textureState.phase === 'ready') {
    setBuildState('正在查看交付 IFF', '地板图案、模型与贴图已从当前交付文件解码。');
  }
}

async function refreshNativePreview() {
  try {
    const response = await fetch('/api/game-preview', { cache: 'no-store' });
    if (!response.ok) throw new Error('请重新启动本地预览服务。');
    nativeStatus = await response.json();
    updateVersions(latestStatus);
    if (previewMode !== 'game') return;
    $('#preview-limit-details').textContent = nativeStatus.manifest?.limitations?.join(' ') || '游戏包预览正在准备；动态球网、球员与比赛行为不在网页中模拟。';
    describeNativeState();
    if (nativeStatus.manifest) await loadManifest(nativeStatus.manifest);
  } catch (error) {
    if (previewMode === 'game') setBuildState('游戏包预览尚未连接', error.message, 'failed');
  }
}

function setPreviewMode(mode) {
  if (!['game', 'source'].includes(mode)) return;
  previewMode = mode;
  ++loadGeneration; loadingBuildId = null;
  $$('[data-preview-mode]').forEach(button => {
    const active = button.dataset.previewMode === mode;
    button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));
  });
  $('#preview-kind').textContent = `NBA 2K26 · ${mode === 'game' ? '游戏包预览' : '编辑源预览'}`;
  $('#rebuild').title = mode === 'game' ? '刷新游戏包预览' : '重新导出源模型';
  $('#preview-scope').textContent = mode === 'game'
    ? '模型和贴图直接来自交付 IFF。网页日光、反射和透明材质为近似显示，最终仍需一次游戏确认。'
    : '正在查看 Blender 编辑源。源文件保存后自动更新；交付包内容请切换到游戏包预览。';
  if (mode === 'game') refreshNativePreview();
  else if (latestStatus) receiveStatus(latestStatus);
}

async function loadManifest(manifest) {
  if (!manifest?.model_url || !renderer) return;
  if (displayedManifest?.build_id === manifest.build_id || loadingBuildId === manifest.build_id) return;
  const generation = ++loadGeneration;
  loadingBuildId = manifest.build_id;
  setBuildState('正在读取新版本', model ? '保留当前画面，完成载入后自动切换。' : manifest.kind === 'native_iff' ? '正在载入交付 IFF 中的模型与贴图。' : '正在载入 Blender 编辑源。', 'building');
  showTextureState('loading', '正在准备地面贴图…');
  textureReport = { build_id: manifest.build_id };
  reportTextureRuntime('loading');
  let gltf;
  try {
    const modelURL = new URL(manifest.model_url, window.location.href);
    if (modelURL.origin !== window.location.origin) throw new Error('预览模型必须来自本地工程服务。');
    modelURL.searchParams.set('build', manifest.build_id);
    const maxSize = [4096, 2048, 1024, 512].find(size => size <= renderer.capabilities.maxTextureSize);
    if (!maxSize) throw new Error('当前显卡的纹理尺寸上限过低，无法显示地面图案。');
    const bundleResponse = await fetch(`/api/preview-textures?build_id=${encodeURIComponent(manifest.build_id)}&max_size=${maxSize}`, { cache: 'no-store' });
    if (!bundleResponse.ok) {
      let message = '请关闭并重新运行 Start_Preview.bat，以启用新的贴图服务。';
      try { const problem = await bundleResponse.json(); if (problem.error && bundleResponse.status !== 404) message = problem.error; } catch {}
      throw new Error(`地面预览贴图准备失败：${message}`);
    }
    const textureBundle = await bundleResponse.json();
    if (generation !== loadGeneration) return;
    if (textureBundle.build_id !== manifest.build_id) throw new Error('模型与贴图构建版本不一致。');
    if (manifest.asset?.sha256 && textureBundle.glb_sha256 !== manifest.asset.sha256) throw new Error('预览贴图与 GLB 文件哈希不一致，请重新构建。');
    const { loader: gltfLoader, failures } = createTextureSafeLoader(textureBundle, window.location.origin);
    textureReport = { build_id: manifest.build_id, texture_transport: 'same-origin-images', preview_max_size: maxSize, images: textureBundle.images.map(({ image_index, original_width, original_height, width, height, source_sha256, preview_sha256, mime_type, transformation }) => ({ image_index, original_width, original_height, width, height, source_sha256, preview_sha256, mime_type, transformation })) };
    gltf = await gltfLoader.loadAsync(modelURL.href);
    if (generation !== loadGeneration) { disposeModel(gltf.scene); return; }
    const replacement = gltf.scene;
    if (!replacement?.children.length) throw new Error('导出的场景为空。');
    if (failures.length) throw new Error(`模型或图片载入失败：${failures[0]}。上一成功版本会继续保留。`);
    const textureInspection = inspectGroundTextures(replacement, renderer.capabilities.maxTextureSize);
    replacement.traverse(node => {
      if (node.isMesh) { node.castShadow = true; node.receiveShadow = true; }
      // Preview uses one stable comparison light rig.
      if (node.isLight) node.visible = false;
    });
    applyLayers(replacement);
    const gpuCheck = await prepareTextureGPU(renderer, replacement, camera, scene, textureInspection.textures);
    if (generation !== loadGeneration) { disposeModel(replacement); return; }
    textureReport = { ...textureReport, ...textureInspection.summary, ...gpuCheck };
    // Preserve the user's framing; rotate it only when switching world orientation.
    const previous = model;
    scene.add(replacement);
    model = replacement;
    if (previous) scene.remove(previous);
    displayedManifest = manifest;
    alignCameraWorld(manifestWorldYaw(manifest));
    $('#empty-state').hidden = true;
    disposeModel(previous);
    renderer.renderLists.dispose();
    updateVersions(latestStatus || { manifest });
    showTextureState('ready', '地面贴图已解码并上传显卡。');
    reportTextureRuntime('ready');
    if (manifest.kind === 'native_iff') {
      loadingBuildId = null; describeNativeState();
    } else if (latestStatus?.phase === 'failed') {
      setBuildState('当前显示旧版', '新版本构建失败，上一成功版本仍可查看。', 'failed', latestStatus.error);
    } else if (latestStatus?.source_version && latestStatus.source_version !== manifest.source_version) {
      setBuildState('当前显示旧版 · 更新中', '源文件已保存，正在构建最新版本。', 'building');
    } else setBuildState('已同步到源工程', '保存模型或图案后，这里会自动更新。');
  } catch (error) {
    if (generation !== loadGeneration) { if (gltf?.scene) disposeModel(gltf.scene); return; }
    if (gltf?.scene && gltf.scene !== model) disposeModel(gltf.scene);
    showTextureState('failed', `地面贴图未就绪：${error.message}`);
    reportTextureRuntime('failed', { error: error.message });
    setBuildState(model ? '当前显示旧版' : '模型载入失败', model ? '新版本未能载入，上一成功版本仍保留。' : '请检查构建日志，修正后重新导出。', 'failed', error.message);
  } finally { if (generation === loadGeneration) loadingBuildId = null; }
}

function receiveStatus(status) {
  latestStatus = status;
  updateVersions(status);
  if (previewMode === 'game') { describeNativeState(); return; }
  if (status.type === 'asset_build_failed' || status.phase === 'failed') {
    setBuildState(model ? '当前显示旧版' : '等待可用模型', model ? '新版本构建失败，上一成功版本仍可查看。' : '源工程尚未成功导出，请查看错误详情。', 'failed', status.error);
  } else if (status.type === 'source_changed' || status.phase === 'building') {
    setBuildState(model ? '当前显示旧版 · 更新中' : '正在构建球场', '已检测到保存，正在从同一源工程导出。', 'building');
  } else if (textureState.phase === 'failed') {
    setBuildState(model ? '当前显示上一成功版本' : '地面贴图载入失败', '图片与显卡检查尚未通过，请查看错误详情。', 'failed', textureState.message);
  } else if (displayedManifest) setBuildState('已同步到源工程', '保存模型或图案后，这里会自动更新。');
  if (status.manifest) loadManifest(status.manifest);
}

const events = new EventSource('/events');
events.onopen = () => { $('#connection-dot').classList.add('connected'); $('#connection-text').textContent = '本地同步已连接'; };
events.onerror = () => { $('#connection-dot').classList.remove('connected'); $('#connection-text').textContent = '正在重连服务'; };
events.onmessage = event => { try { receiveStatus(JSON.parse(event.data)); } catch (error) { console.error('Invalid server event', error); } };

$$('[data-view]').forEach(button => button.addEventListener('click', () => chooseView(button.dataset.view)));
$$('[data-preview-mode]').forEach(button => button.addEventListener('click', () => setPreviewMode(button.dataset.previewMode)));
$('#reset-view').addEventListener('click', () => chooseView('overview'));
$$('[data-layer]').forEach(input => {
  input.checked = layerState[input.dataset.layer] ?? true;
  input.addEventListener('change', () => { layerState[input.dataset.layer] = input.checked; applyLayers(); persist(); });
});
$$('[data-category]').forEach(input => {
  input.checked = categoryState[input.dataset.category] ?? true;
  input.addEventListener('change', () => { categoryState[input.dataset.category] = input.checked; applyLayers(); showTextureState(); persist(); });
});
$('#wireframe').checked = wireframe;
$('#wireframe').addEventListener('change', event => { wireframe = event.target.checked; applyLayers(); persist(); });
$('#rebuild').addEventListener('click', async () => {
  $('#rebuild').disabled = true;
  try {
    if (previewMode === 'game') { await refreshNativePreview(); return; }
    const response = await fetch('/api/rebuild', { method: 'POST' });
    if (!response.ok) throw new Error('服务没有接受重建请求。');
    setBuildState('等待重新构建', '已加入构建队列，将保留上次成功画面。', 'building');
  } catch (error) { setBuildState(model ? '当前显示旧版' : '服务连接失败', '请确认预览启动窗口仍然打开。', 'failed', error.message); }
  finally { $('#rebuild').disabled = false; }
});

function showReference(index) {
  if (!references.length) return;
  referenceIndex = (index + references.length) % references.length;
  const item = references[referenceIndex];
  const url = item.url || item.src || item.file;
  $('#reference-image').src = url.startsWith('/') ? url : `/references/${url}`;
  $('#reference-image').alt = item.title || item.caption || `参考照片 ${referenceIndex + 1}`;
  $('#reference-image').hidden = false;
  $('#reference-placeholder').hidden = true;
  $('#reference-image-button').disabled = false;
  $('#reference-count').textContent = `${String(referenceIndex + 1).padStart(2, '0')} / ${references.length}`;
  $('#reference-caption').textContent = item.title || item.caption || `原始参考照片 ${referenceIndex + 1}`;
  $('#reference-select').value = String(referenceIndex);
}
$('#reference-select').addEventListener('change', event => {
  const index = Number(event.target.value);
  if (Number.isInteger(index) && index >= 0 && index < references.length) showReference(index);
});
$('#reference-prev').addEventListener('click', () => showReference(referenceIndex - 1));
$('#reference-next').addEventListener('click', () => showReference(referenceIndex + 1));
$('#reference-image-button').addEventListener('click', () => {
  $('#reference-large').src = $('#reference-image').src;
  $('#reference-large').alt = $('#reference-image').alt;
  $('#reference-large-caption').textContent = $('#reference-caption').textContent;
  $('#reference-dialog').showModal();
});
$('#close-reference').addEventListener('click', () => $('#reference-dialog').close());
$('#reference-dialog').addEventListener('click', event => { if (event.target === $('#reference-dialog')) $('#reference-dialog').close(); });
$('#reference-image').addEventListener('error', () => {
  $('#reference-placeholder').hidden = false;
  $('#reference-placeholder').textContent = '这张参考照片暂时无法读取';
  $('#reference-image').hidden = true;
  $('#reference-image-button').disabled = true;
});
async function loadReferences() {
  try {
    const response = await fetch('/references/index.json', { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    references = (Array.isArray(data) ? data : data.images || data.references || []).map(item => typeof item === 'string' ? { url: item } : item).filter(item => item.url || item.src || item.file);
    const options = references.map((item, index) => {
      const option = document.createElement('option');
      option.value = String(index);
      option.textContent = item.title || item.caption || `参考图 ${String(index + 1).padStart(2, '0')}`;
      return option;
    });
    $('#reference-select').replaceChildren(...options);
    $('#reference-select').disabled = references.length === 0;
    showReference(referenceIndex);
  } catch (error) { console.warn('Reference index unavailable', error); }
}
fetch('/api/config').then(response => response.json()).then(config => {
  referenceSign = config.preview?.reference_sign === 1 ? 1 : -1;
  chilisViews = config.preview?.chilis_views || {};
  if (!saved.camera) chooseView(currentView, false);
}).catch(() => {});
loadReferences();
refreshNativePreview();
setInterval(refreshNativePreview, 5000);
// References can arrive after the first export while source modeling continues.
setInterval(() => { if (!references.length) loadReferences(); }, 15000);
window.addEventListener('beforeunload', () => { events.close(); disposeModel(model); renderer?.dispose(); });
