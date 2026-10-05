import { promises as fs, createWriteStream } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { EventEmitter } from 'node:events';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const INPUT_DIRS = ['source', 'artwork', 'config'];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
export const readJSON = async (filename, fallback = null) => {
  try { return JSON.parse(await fs.readFile(filename, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return fallback; throw error; }
};

async function inputFiles(root, directory) {
  let entries;
  try { entries = await fs.readdir(path.join(root, directory), { withFileTypes: true }); }
  catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  const files = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
    if (entry.name.startsWith('.') || /(?:\.blend\d+|\.tmp|\.bak|~)$/i.test(entry.name)) continue;
    const relative = path.join(directory, entry.name);
    // These are deterministic products of editable court/context SVG sources.
    // Watching them would create a build loop when rasterization replaces them.
    if (['artwork/court.png', 'artwork/paving-atlas.png', 'artwork/paving-atlas.svg'].includes(relative.split(path.sep).join('/'))) continue;
    if (directory === 'source' && (/\.glb$/i.test(entry.name) || entry.name === 'geometry_validation.json')) continue;
    if (entry.isDirectory()) files.push(...await inputFiles(root, relative));
    else if (entry.isFile()) files.push(relative);
  }
  return files;
}

export async function hashInputs(root = ROOT) {
  const hash = createHash('sha256');
  const files = [];
  for (const directory of INPUT_DIRS) {
    for (const relative of await inputFiles(root, directory)) {
      const content = await fs.readFile(path.join(root, relative));
      const digest = createHash('sha256').update(content).digest('hex');
      const normalized = relative.split(path.sep).join('/');
      hash.update(normalized).update('\0').update(digest).update('\0');
      files.push({ path: normalized, sha256: digest, bytes: content.length });
    }
  }
  // Exporter changes must invalidate existing output, without watching any output directory.
  for (const relative of ['tools/export_scene.py', 'tools/rasterize_artwork.mjs', 'tools/create_scene.py']) {
    try {
      const content = await fs.readFile(path.join(root, relative));
      const digest = createHash('sha256').update(content).digest('hex');
      hash.update(relative).update('\0').update(digest).update('\0');
      files.push({ path: relative, sha256: digest, bytes: content.length });
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  return { hash: hash.digest('hex'), files };
}

export async function validateGLB(filename) {
  const data = await fs.readFile(filename);
  if (data.length < 20 || data.toString('ascii', 0, 4) !== 'glTF' || data.readUInt32LE(4) !== 2 || data.readUInt32LE(8) !== data.length) {
    throw new Error('导出文件不是完整的 glTF 2.0 GLB。');
  }
  const jsonLength = data.readUInt32LE(12);
  if (data.readUInt32LE(16) !== 0x4E4F534A || 20 + jsonLength > data.length) throw new Error('GLB JSON 数据段不完整。');
  const json = JSON.parse(data.toString('utf8', 20, 20 + jsonLength).trim());
  if (!json.scenes?.length || !json.nodes?.length || !json.meshes?.length) throw new Error('GLB 未包含可显示的真实场景。');
  for (const item of [...(json.buffers || []), ...(json.images || [])]) {
    if (item.uri && !item.uri.startsWith('data:')) throw new Error('GLB 引用了外部文件；预览发布要求纹理和网格完整内嵌。');
  }
  return { bytes: data.length, sha256: createHash('sha256').update(data).digest('hex'), meshes: json.meshes.length, nodes: json.nodes.length };
}

export class BuildWatcher extends EventEmitter {
  constructor(root = ROOT) {
    super();
    this.root = root;
    this.state = { phase: 'waiting', source_version: null, build_id: null, error: null, manifest: null };
    this.running = false;
    this.pending = null;
    this.lastObserved = null;
    this.stopped = false;
  }

  publish(type, data = {}) {
    this.emit('event', { type, ...this.state, ...data, time: new Date().toISOString() });
  }

  async start() {
    this.timer = setInterval(() => this.scan().catch(error => this.watchError(error)), 1200);
    try {
      this.state.manifest = await readJSON(path.join(this.root, 'public/manifest.json'));
      await this.scan(true);
    } catch (error) { this.watchError(error); }
  }

  watchError(error) {
    this.state.error = `读取源文件失败：${error.message}`;
    this.publish('asset_build_failed');
  }

  async scan(initial = false) {
    if (this.scanning || this.stopped) return;
    this.scanning = true;
    try {
      const inputs = await hashInputs(this.root);
      if (inputs.hash !== this.lastObserved) {
        this.lastObserved = inputs.hash;
        this.state.source_version = `S-${inputs.hash.slice(0, 10)}`;
        this.publish('source_changed');
        if (initial && this.state.manifest?.input_hash === inputs.hash) {
          this.state.phase = 'ready';
          this.state.build_id = this.state.manifest.build_id;
          this.publish('asset_build_ready');
        } else this.request(inputs);
      }
    } finally { this.scanning = false; }
  }

  async rebuild() { this.request(await hashInputs(this.root)); }

  request(inputs) {
    this.pending = inputs;
    this.state.source_version = `S-${inputs.hash.slice(0, 10)}`;
    clearTimeout(this.debounce);
    this.debounce = setTimeout(() => this.drain(), 850);
  }

  async drain() {
    if (this.running || this.stopped || !this.pending) return;
    const inputs = this.pending;
    this.pending = null;
    this.running = true;
    try { await this.build(inputs); }
    catch (error) {
      this.state.phase = 'failed';
      this.state.error = error.message;
      this.publish('asset_build_failed');
    } finally {
      this.running = false;
      if (this.pending && !this.stopped) this.debounce = setTimeout(() => this.drain(), 500);
    }
  }

  async build(inputs) {
    const buildId = `${new Date().toISOString().replace(/[-:.]/g, '')}-${inputs.hash.slice(0, 8)}`;
    const sourceVersion = `S-${inputs.hash.slice(0, 10)}`;
    this.state.phase = 'building';
    this.state.error = null;
    this.state.build_id = buildId;
    this.publish('asset_build_started', { building_source_version: sourceVersion });
    const config = await readJSON(path.join(this.root, 'config/project.json'), {});
    const blender = process.env.ZGC_BLENDER || config.tools?.blender_path || config.tools?.blender?.path || config.blender_path;
    if (!blender) throw new Error('未配置 Blender：请在 config/project.json 中设置 tools.blender_path。');
    const blend = path.join(this.root, 'source/scene.blend');
    const exporter = path.join(this.root, 'tools/export_scene.py');
    await fs.access(blend).catch(() => { throw new Error('等待源模型 source/scene.blend。'); });
    await fs.access(exporter).catch(() => { throw new Error('等待导出脚本 tools/export_scene.py。'); });
    const staging = path.join(this.root, '.build-staging', buildId);
    const output = path.join(staging, 'scene.glb');
    const logDir = path.join(this.root, 'logs');
    await fs.mkdir(staging, { recursive: true });
    await fs.mkdir(logDir, { recursive: true });
    const logPath = path.join(logDir, `${buildId}.log`);
    const log = createWriteStream(logPath);
    log.write(`${JSON.stringify({ build_id: buildId, source_version: sourceVersion, input_hash: inputs.hash, blender, inputs: inputs.files }, null, 2)}\n`);
    let tail = '';
    try {
      const run = (executable, args, label) => new Promise((resolve, reject) => {
        log.write(`\n${label}\n`);
        const child = spawn(executable, args, {
          cwd: this.root, windowsHide: true,
          env: { ...process.env, ZGC_BUILD_ID: buildId, ZGC_SOURCE_VERSION: sourceVersion },
        });
        this.child = child;
        const onData = chunk => { log.write(chunk); tail = (tail + chunk.toString()).slice(-8000); };
        child.stdout.on('data', onData);
        child.stderr.on('data', onData);
        child.on('error', reject);
        child.on('close', code => {
          this.child = null;
          code === 0 ? resolve() : reject(new Error(`${label}失败（退出码 ${code}）。${tail.slice(-1400)}`));
        });
      });
      await run(process.execPath, [path.join(this.root, 'tools/rasterize_artwork.mjs')], '地面 SVG 栅格化');
      await run(blender, ['--background', blend, '--python-exit-code', '1', '--python', exporter, '--', '--output', output, '--project', path.join(this.root, 'config/project.json')], 'Blender 导出');
      const asset = await validateGLB(output);
      const after = await hashInputs(this.root);
      if (after.hash !== inputs.hash) {
        this.lastObserved = after.hash;
        this.request(after);
        log.write('\nSource changed during export. Discarded this unpublished output; rebuilding latest saved inputs.\n');
        this.publish('source_changed', { superseded_build_id: buildId });
        return;
      }
      const builds = path.join(this.root, 'public/builds');
      await fs.mkdir(builds, { recursive: true });
      await fs.writeFile(path.join(staging, 'build.json'), JSON.stringify({ build_id: buildId, source_version: sourceVersion, input_hash: inputs.hash, inputs: inputs.files, asset, blender, node: process.version, exported_at: new Date().toISOString() }, null, 2));
      // Directory and manifest rename keep incomplete GLBs invisible to clients.
      await fs.rename(staging, path.join(builds, buildId));
      const previous = await readJSON(path.join(this.root, 'public/manifest.json'), {});
      const manifest = {
        schema_version: 1,
        build_id: buildId,
        source_version: sourceVersion,
        preview_version: sourceVersion,
        iff_version: previous.iff_version ?? null,
        game_verified_version: previous.game_verified_version ?? null,
        model_url: `/builds/${buildId}/scene.glb`,
        input_hash: inputs.hash,
        asset,
        built_at: new Date().toISOString(),
        log_url: `/logs/${buildId}.log`,
      };
      const tempManifest = path.join(this.root, 'public', `.manifest-${buildId}.json`);
      await fs.writeFile(tempManifest, `${JSON.stringify(manifest, null, 2)}\n`);
      let renamed = false;
      for (let attempt = 0; attempt < 5; attempt++) {
        try { await fs.rename(tempManifest, path.join(this.root, 'public/manifest.json')); renamed = true; break; }
        catch (error) { if (!['EPERM', 'EACCES', 'EBUSY'].includes(error.code) || attempt === 4) throw error; await delay(120); }
      }
      if (!renamed) throw new Error('无法原子更新预览清单。');
      this.state.manifest = manifest;
      this.state.source_version = sourceVersion;
      this.state.phase = 'ready';
      this.state.error = null;
      this.publish('asset_build_ready');
    } finally {
      await new Promise(resolve => log.end(resolve));
      // Keep failed staging artifacts and logs for diagnosis. Never alter source files.
    }
  }

  stop() {
    this.stopped = true;
    clearInterval(this.timer);
    clearTimeout(this.debounce);
    this.child?.kill();
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const watcher = new BuildWatcher();
  watcher.on('event', event => console.log(JSON.stringify(event)));
  if (process.argv.includes('--once')) {
    try {
      const inputs = await hashInputs();
      watcher.state.source_version = `S-${inputs.hash.slice(0, 10)}`;
      await watcher.build(inputs);
      if (watcher.pending) { console.error('构建期间源文件改变，请重新运行构建。'); process.exitCode = 2; }
    } catch (error) { console.error(error.message); process.exitCode = 1; }
    finally { watcher.stop(); }
  } else {
    await watcher.start();
    process.on('SIGINT', () => { watcher.stop(); process.exit(); });
  }
}
