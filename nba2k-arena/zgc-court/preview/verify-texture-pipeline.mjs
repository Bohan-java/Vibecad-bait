// Offline integration: actual GLTFLoader and HTTP images, with Sharp decoding.
// This does not replace browser/GPU/visual verification.
import { readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';
import * as THREE from './vendor/three/build/three.module.js';

const projectURL = new URL('../', import.meta.url);
const readJSON = async file => JSON.parse(await readFile(new URL(file, projectURL), 'utf8'));
const config = await readJSON('config/project.json');
const sharp = createRequire(import.meta.url)(config.tools.sharp_module);
const origin = `http://127.0.0.1:${config.preview.port}`;
const manifest = await readJSON('public/manifest.json');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const pipelineSource = (await readFile(new URL('texture-pipeline.js', import.meta.url), 'utf8'))
  .replace("from 'three'", `from '${new URL('vendor/three/build/three.module.js', import.meta.url).href}'`)
  .replace("from 'three/addons/loaders/GLTFLoader.js'", `from '${new URL('vendor/three/examples/jsm/loaders/GLTFLoader.js', import.meta.url).href}'`);
const { createTextureSafeLoader, inspectGroundTextures } = await import(`data:text/javascript;base64,${Buffer.from(pipelineSource).toString('base64')}`);
globalThis.self = { URL };
const builds = [...new Set(['20261004T032047007Z-6b3c3492', manifest.build_id])];
const results = [];
for (const buildId of builds) {
  const response = await fetch(`${origin}/api/preview-textures?build_id=${buildId}&max_size=4096`);
  assert.equal(response.status, 200);
  const bundle = await response.json();
  assert.equal(bundle.schema_version, 2);
  const glb = await readFile(new URL(`public/builds/${buildId}/scene.glb`, projectURL));
  assert.equal(bundle.glb_sha256, hash(glb));
  const requests = [];
  const decoded = new Map();
  const adapter = {
    setCrossOrigin() {},
    load(url, onLoad, onProgress, onError) {
      (async () => {
        assert.equal(new URL(url).origin, origin);
        assert.ok(new URL(url).pathname.startsWith('/preview-textures/'));
        const imageResponse = await fetch(url);
        assert.equal(imageResponse.status, 200);
        const bytes = Buffer.from(await imageResponse.arrayBuffer());
        const info = bundle.images.find(item => new URL(item.url, origin).href === url);
        assert.ok(info);
        assert.equal(hash(bytes), info.preview_sha256);
        if (info.transformation === 'byte-preserved') assert.equal(info.source_sha256, info.preview_sha256);
        const raw = await sharp(bytes).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
        assert.equal(raw.info.width, info.width);
        assert.equal(raw.info.height, info.height);
        requests.push(url);
        decoded.set(info.image_index, { image_index: info.image_index, width: info.width, height: info.height, transformation: info.transformation, byte_preserved: info.source_sha256 === info.preview_sha256 });
        onLoad(new THREE.Texture({ width: raw.info.width, height: raw.info.height, data: raw.data }));
      })().catch(onError);
    },
  };
  const { loader, failures } = createTextureSafeLoader(bundle, origin, adapter);
  const asset = await loader.parseAsync(glb.buffer.slice(glb.byteOffset, glb.byteOffset + glb.byteLength), `${origin}/`);
  assert.equal(failures.length, 0);
  const inspected = inspectGroundTextures(asset.scene, 16384);
  const slots = [...new Set(inspected.summary.texture_checks.map(item => item.slot))];
  if (buildId === manifest.build_id && buildId !== builds[0]) {
    for (const slot of ['map', 'normalMap', 'roughnessMap', 'metalnessMap']) assert.ok(slots.includes(slot), `${slot} missing`);
  }
  let court;
  asset.scene.traverse(node => { if (node.name === 'court_surface') court = node; });
  assert.ok(court?.material.map);
  const map = court.material.map;
  court.material.map = null;
  assert.throws(() => inspectGroundTextures(asset.scene, 16384), /地面贴图未加载/);
  court.material.map = map;
  const uv = court.geometry.getAttribute('uv1');
  court.geometry.deleteAttribute('uv1');
  assert.throws(() => inspectGroundTextures(asset.scene, 16384), /纹理坐标/);
  court.geometry.setAttribute('uv1', uv);
  assert.throws(() => inspectGroundTextures(asset.scene, 2048), /超过当前显卡上限/);
  const previousSpace = map.colorSpace;
  map.colorSpace = THREE.NoColorSpace;
  assert.throws(() => inspectGroundTextures(asset.scene, 16384), /颜色空间不匹配/);
  map.colorSpace = previousSpace;
  results.push({ build_id: buildId, glb_sha256: hash(glb), status: 'passed', ...inspected.summary, decoded_images: [...decoded.values()], texture_request_count: requests.length, tested_rejections: ['missing_ground_image', 'missing_uv1', 'gpu_dimension_limit', 'incorrect_color_space'] });
  const materials = new Set();
  asset.scene.traverse(node => { node.geometry?.dispose(); for (const material of Array.isArray(node.material) ? node.material : [node.material]) if (material) materials.add(material); });
  inspected.textures.forEach(texture => texture.dispose());
  materials.forEach(material => material.dispose());
}
const report = { checked_at: new Date().toISOString(), scope: 'Real GLTFLoader parse and real HTTP image bytes decoded by Sharp through an offline adapter. No browser, canvas or GPU in this test.', results };
await writeFile(new URL('texture-pbr-verification.json', import.meta.url), JSON.stringify(report, null, 2));
console.log(JSON.stringify(results.map(result => ({ build_id: result.build_id, status: result.status, images: result.decoded_images.length, texture_slots: [...new Set(result.texture_checks.map(item => item.slot))], unique_textures: result.checked_unique_textures })), null, 2));
