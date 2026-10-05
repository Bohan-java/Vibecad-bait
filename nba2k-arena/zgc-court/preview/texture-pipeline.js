import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

// Only decoded image transport is adapted. Geometry, materials' UV channel
// assignments, samplers and the source GLB remain unchanged.
export function createTextureSafeLoader(bundle, origin, imageLoader = null) {
  const failures = [];
  const manager = new THREE.LoadingManager();
  manager.onError = url => failures.push(String(url));
  const loader = new GLTFLoader(manager);
  loader.register(parser => ({
    name: 'ZGC_same_origin_preview_images',
    beforeRoot() {
      const definitions = parser.json.images || [];
      if (definitions.length !== bundle.images.length) throw new Error('预览贴图目录与 GLB 不一致，请重新构建。');
      for (const [index, definition] of definitions.entries()) {
        const preview = bundle.images.find(item => item.image_index === index);
        if (!preview) throw new Error(`GLB 图片 ${index} 缺少可用的预览贴图。`);
        const url = new URL(preview.url, origin);
        if (url.origin !== origin || !url.pathname.startsWith('/preview-textures/')) throw new Error('预览贴图必须来自本项目本地服务。');
        definition.uri = url.href;
        definition.mimeType = preview.mime_type;
        delete definition.bufferView;
      }
      // HTMLImageElement avoids the blob/ImageBitmap route and its large-image
      // decode allocation. Oversized images use <=4K copies from this exact GLB;
      // smaller PBR images retain their original bytes.
      parser.textureLoader = imageLoader || new THREE.TextureLoader(manager);
      parser.textureLoader.setCrossOrigin?.('anonymous');
    },
  }));
  return { loader, failures };
}

export function inspectGroundTextures(root, maxTextureSize) {
  const textures = new Set();
  const checks = [];
  const textureChecks = new Map();
  const colorSlots = new Set(['map', 'emissiveMap', 'sheenColorMap', 'specularColorMap']);
  const dataSlots = new Set(['normalMap', 'roughnessMap', 'metalnessMap', 'aoMap', 'bumpMap', 'alphaMap', 'clearcoatMap', 'clearcoatNormalMap', 'clearcoatRoughnessMap', 'transmissionMap', 'thicknessMap', 'sheenRoughnessMap', 'specularIntensityMap', 'iridescenceMap', 'iridescenceThicknessMap', 'anisotropyMap']);
  root.traverse(node => {
    if (!node.isMesh) return;
    for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
      if (!material) continue;
      const required = material.userData?.ground_artwork_mode === 'world-paving-atlas' || material.name === 'Court | editable artwork';
      if (required && !material.map?.image) throw new Error(`地面贴图未加载：${node.name}。GLB 几何可读不代表贴图已加载。`);
      for (const [slot, map] of Object.entries(material)) {
        if (!map?.isTexture || (!colorSlots.has(slot) && !dataSlots.has(slot))) continue;
        const image = map.image;
        const width = image?.naturalWidth || image?.width || 0;
        const height = image?.naturalHeight || image?.height || 0;
        if (!width || !height) throw new Error(`材质图片未成功解码：${node.name} / ${slot}。`);
        if (Math.max(width, height) > maxTextureSize) throw new Error(`材质贴图 ${width}×${height} 超过当前显卡上限 ${maxTextureSize}。`);
        const channel = map.channel || 0;
        const attribute = channel === 0 ? 'uv' : `uv${channel}`;
        if (!node.geometry.getAttribute(attribute)) throw new Error(`${node.name} 的 ${slot} 需要 ${attribute}，但模型没有该纹理坐标。`);
        const expectedSpace = colorSlots.has(slot) ? THREE.SRGBColorSpace : THREE.NoColorSpace;
        if (map.colorSpace !== expectedSpace) throw new Error(`${material.name} 的 ${slot} 颜色空间不匹配。`);
        textures.add(map);
        const check = { object: node.name, material: material.name, slot, width, height, uv_channel: channel, uv_attribute: attribute, color_space: map.colorSpace, wrap_s: map.wrapS, wrap_t: map.wrapT };
        textureChecks.set(`${map.uuid}/${slot}`, check);
        if (required && slot === 'map') checks.push(check);
      }
    }
  });
  if (!checks.length) throw new Error('没有找到可核验的球场地面图案材质。');
  return { textures: [...textures], summary: { checked_ground_meshes: checks.length, checked_unique_textures: textures.size, checks, texture_checks: [...textureChecks.values()] } };
}

export async function prepareTextureGPU(renderer, root, camera, scene, textures) {
  const gl = renderer.getContext();
  if (gl.isContextLost()) throw new Error('显卡绘图上下文已丢失，请刷新预览。');
  for (let count = 0; count < 8 && gl.getError() !== gl.NO_ERROR; count++) {}
  const shaderErrors = [];
  const oldHandler = renderer.debug.onShaderError;
  renderer.debug.onShaderError = (context, program, vertex, fragment) => {
    shaderErrors.push([context.getProgramInfoLog(program), context.getShaderInfoLog(vertex), context.getShaderInfoLog(fragment)].filter(Boolean).join('\n'));
  };
  try {
    for (const texture of textures) renderer.initTexture(texture);
    const uploadError = gl.getError();
    if (uploadError !== gl.NO_ERROR) throw new Error(`材质贴图上传显卡失败（WebGL 0x${uploadError.toString(16)}）。请关闭占用显存的窗口后重试。`);
    await renderer.compileAsync(root, camera, scene);
    if (shaderErrors.length) throw new Error(`材质着色程序未能编译：${shaderErrors[0].slice(0, 1200)}`);
    if (gl.isContextLost()) throw new Error('载入材质贴图时显卡上下文丢失。');
    const compileError = gl.getError();
    if (compileError !== gl.NO_ERROR) throw new Error(`场景准备失败（WebGL 0x${compileError.toString(16)}）。`);
    return { texture_upload: 'passed', material_compile: 'passed' };
  } finally { renderer.debug.onShaderError = oldHandler; }
}
