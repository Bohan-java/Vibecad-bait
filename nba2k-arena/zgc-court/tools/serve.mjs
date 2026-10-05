import http from 'node:http';
import path from 'node:path';
import { promises as fs, createReadStream } from 'node:fs';
import { spawn } from 'node:child_process';
import { randomUUID, timingSafeEqual, createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { ROOT, BuildWatcher, readJSON } from './watch_build.mjs';

const project = await readJSON(path.join(ROOT, 'config/project.json'), {});
const portArgument = process.argv.indexOf('--port');
const port = Number(portArgument >= 0 ? process.argv[portArgument + 1] : process.env.ZGC_PORT || project.preview?.port || 4173);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('预览端口必须在 1024–65535 之间。');
const watcher = new BuildWatcher(ROOT);
const clients = new Set();
const identity = { service: 'zgc-court-preview', project_root: await fs.realpath(ROOT), instance_id: randomUUID(), pid: process.pid, port, started_at: new Date().toISOString() };
const controlToken = randomUUID();
const runtimeDirectory = path.join(ROOT, '.preview-runtime');
const stateFile = path.join(runtimeDirectory, `server-${port}.json`);
let stopping = false;
const require = createRequire(import.meta.url);
const textureJobs = new Map();
const textureCacheRoot = path.join(runtimeDirectory, 'textures');
const diagnosticsFile = path.join(ROOT, 'preview', 'texture-runtime-report.json');
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.glb': 'model/gltf-binary', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.log': 'text/plain; charset=utf-8', '.txt': 'text/plain; charset=utf-8' };
const sendJSON = (response, status, value) => { response.writeHead(status, { 'Content-Type': mime['.json'], 'Cache-Control': 'no-store' }); response.end(JSON.stringify(value)); };

async function publicationState() {
  // Game delivery can complete after the GLB build. Refresh only its status
  // fields for this exact asset; never replace a running/failed build state.
  const latest = await readJSON(path.join(ROOT, 'public/manifest.json'));
  const current = watcher.state.manifest;
  if (current && latest?.build_id === current.build_id && latest.source_version === current.source_version && latest.asset?.sha256 === current.asset?.sha256) {
    watcher.state.manifest = { ...current, iff_version: latest.iff_version ?? null, game_verified_version: latest.game_verified_version ?? null };
  }
  return watcher.state;
}

async function gamePreviewState() {
  const manifest = await readJSON(path.join(ROOT, 'public/game-preview/manifest.json'));
  if (!manifest) return { phase: 'waiting', manifest: null };
  try {
    const current = await fs.stat(path.join(ROOT, 'output', 'arena_700_int.iff'));
    const matches = current.size === manifest.iff?.bytes && Math.abs(current.mtimeMs - Number(manifest.iff?.mtime_ns) / 1e6) < 2;
    return { phase: matches ? 'ready' : 'stale', manifest, matches_current_iff: matches };
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    return { phase: 'stale', manifest, matches_current_iff: false };
  }
}

function openBrowser(url) {
  if (process.platform === 'win32') spawn('rundll32.exe', ['url.dll,FileProtocolHandler', url], { detached: true, stdio: 'ignore', windowsHide: true }).unref();
  else spawn(process.platform === 'darwin' ? 'open' : 'xdg-open', [url], { detached: true, stdio: 'ignore' }).unref();
}

async function previewTextures(buildId, maxSize) {
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,100}$/.test(buildId) || ![512, 1024, 2048, 4096].includes(maxSize)) {
    throw new Error('预览贴图构建号或尺寸无效。');
  }
  const key = `${buildId}/${maxSize}`;
  if (textureJobs.has(key)) return textureJobs.get(key);
  const job = (async () => {
    let modelPath = path.join(ROOT, 'public', 'builds', buildId, 'scene.glb');
    if (buildId.startsWith('iff-')) {
      const native = await gamePreviewState();
      if (native.manifest?.build_id !== buildId) throw new Error('游戏包预览已经更新，请刷新页面。');
      modelPath = path.join(ROOT, 'public/game-preview/current.glb');
    }
    const outputDirectory = path.join(textureCacheRoot, buildId, String(maxSize));
    const indexPath = path.join(outputDirectory, 'index.json');
    const cached = await readJSON(indexPath);
    if (cached?.schema_version === 2 && cached.build_id === buildId && cached.max_size === maxSize) {
      try {
        await Promise.all(cached.images.map(item => fs.access(path.join(outputDirectory, item.file))));
        return cached;
      } catch (error) { if (error.code !== 'ENOENT') throw error; }
    }
    const model = await fs.readFile(modelPath);
    if (model.length < 28 || model.toString('ascii', 0, 4) !== 'glTF' || model.readUInt32LE(4) !== 2 || model.readUInt32LE(8) !== model.length) throw new Error('构建的 GLB 不完整，无法读取贴图。');
    const jsonLength = model.readUInt32LE(12);
    const binaryHeader = 20 + jsonLength;
    if (binaryHeader + 8 > model.length || model.readUInt32LE(binaryHeader + 4) !== 0x004e4942) throw new Error('GLB 缺少内嵌二进制数据。');
    const doc = JSON.parse(model.toString('utf8', 20, binaryHeader).trim());
    const binaryStart = binaryHeader + 8;
    const latestProject = await readJSON(path.join(ROOT, 'config/project.json'), {});
    if (!latestProject.tools?.sharp_module) throw new Error('未配置本地贴图缩放工具 tools.sharp_module。');
    const sharp = require(latestProject.tools.sharp_module);
    await fs.mkdir(outputDirectory, { recursive: true });
    const images = [];
    for (const [imageIndex, source] of (doc.images || []).entries()) {
      const view = doc.bufferViews?.[source.bufferView];
      if (!view || source.uri || view.buffer !== 0) throw new Error(`GLB 图片 ${imageIndex} 不是独立内嵌图片。`);
      const start = binaryStart + (view.byteOffset || 0), end = start + view.byteLength;
      if (start < binaryStart || end > model.length || end <= start) throw new Error('GLB 图片数据越界。');
      const original = model.subarray(start, end);
      const originalHash = createHash('sha256').update(original).digest('hex');
      const metadata = await sharp(original).metadata();
      // Small PBR maps keep their encoded bytes, including normal/MR channels.
      // Only oversized images need a lower-memory preview derivative.
      const unchanged = Math.max(metadata.width, metadata.height) <= maxSize && ['png', 'jpeg'].includes(metadata.format);
      const resized = unchanged ? { data: original, info: metadata } : await sharp(original).resize({ width: maxSize, height: maxSize, fit: 'inside', withoutEnlargement: true }).png().toBuffer({ resolveWithObject: true });
      const imageType = unchanged && metadata.format === 'jpeg' ? 'image/jpeg' : 'image/png';
      const previewHash = createHash('sha256').update(resized.data).digest('hex');
      const filename = `${imageIndex}-${previewHash.slice(0, 20)}.${imageType === 'image/jpeg' ? 'jpg' : 'png'}`;
      const finalPath = path.join(outputDirectory, filename);
      const tempPath = `${finalPath}.${randomUUID()}.tmp`;
      await fs.writeFile(tempPath, resized.data);
      await fs.rename(tempPath, finalPath);
      images.push({ image_index: imageIndex, name: source.name || `image-${imageIndex}`, file: filename, url: `/preview-textures/${buildId}/${maxSize}/${filename}`, mime_type: imageType, transformation: unchanged ? 'byte-preserved' : 'resized', source_sha256: originalHash, preview_sha256: previewHash, original_width: metadata.width, original_height: metadata.height, width: resized.info.width, height: resized.info.height, bytes: resized.data.length });
    }
    const result = { schema_version: 2, build_id: buildId, max_size: maxSize, glb_sha256: createHash('sha256').update(model).digest('hex'), images };
    const tempIndex = `${indexPath}.${randomUUID()}.tmp`;
    await fs.writeFile(tempIndex, JSON.stringify(result, null, 2));
    await fs.rename(tempIndex, indexPath);
    return result;
  })();
  textureJobs.set(key, job);
  try { return await job; } catch (error) { textureJobs.delete(key); throw error; }
}

async function savePreviewDiagnostics(request) {
  let size = 0;
  const chunks = [];
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 262144) throw new Error('贴图诊断数据过大。');
    chunks.push(chunk);
  }
  const data = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  if (data.schema_version !== 1 || !['loading', 'ready', 'failed', 'context_lost'].includes(data.phase)) throw new Error('贴图诊断格式无效。');
  const tempPath = `${diagnosticsFile}.${randomUUID()}.tmp`;
  await fs.writeFile(tempPath, JSON.stringify({ ...data, received_at: new Date().toISOString() }, null, 2));
  await fs.rename(tempPath, diagnosticsFile);
}

async function sendFile(request, response, base, relative, immutable = false) {
  const target = path.resolve(base, relative);
  if (target !== base && !target.startsWith(base + path.sep)) return sendJSON(response, 403, { error: '路径不允许' });
  try {
    const real = await fs.realpath(target);
    if (real !== base && !real.startsWith(base + path.sep)) return sendJSON(response, 403, { error: '路径不允许' });
    const stat = await fs.stat(real);
    if (!stat.isFile()) return sendJSON(response, 404, { error: '文件不存在' });
    response.writeHead(200, { 'Content-Type': mime[path.extname(real).toLowerCase()] || 'application/octet-stream', 'Content-Length': stat.size, 'Cache-Control': immutable ? 'public, max-age=31536000, immutable' : 'no-store', 'X-Content-Type-Options': 'nosniff' });
    if (request.method === 'HEAD') response.end(); else createReadStream(real).pipe(response);
  } catch (error) {
    sendJSON(response, error.code === 'ENOENT' ? 404 : 500, { error: error.code === 'ENOENT' ? '文件不存在' : error.message });
  }
}

const server = http.createServer(async (request, response) => {
  try {
    // Localhost-only binding plus Host/Origin checks prevent accidental remote access and DNS rebinding.
    const host = request.headers.host;
    if (![ `127.0.0.1:${port}`, `localhost:${port}` ].includes(host)) return sendJSON(response, 403, { error: '仅允许本机访问' });
    if (request.headers.origin && ![`http://127.0.0.1:${port}`, `http://localhost:${port}`].includes(request.headers.origin)) return sendJSON(response, 403, { error: '来源不允许' });
    const url = new URL(request.url, `http://127.0.0.1:${port}`);
    const pathname = decodeURIComponent(url.pathname);
    if (pathname === '/api/preview-diagnostics' && request.method === 'POST') {
      await savePreviewDiagnostics(request);
      return sendJSON(response, 200, { ok: true });
    }
    if (pathname === '/api/shutdown' && request.method === 'POST') {
      const supplied = Buffer.from(String(request.headers['x-zgc-control'] || ''));
      const expected = Buffer.from(controlToken);
      if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) return sendJSON(response, 403, { error: '服务身份校验失败，未停止任何程序。' });
      sendJSON(response, 200, { stopping: true, instance_id: identity.instance_id });
      setImmediate(stop);
      return;
    }
    if (pathname === '/api/rebuild' && request.method === 'POST') { await watcher.rebuild(); return sendJSON(response, 202, { ok: true }); }
    if (!['GET', 'HEAD'].includes(request.method)) return sendJSON(response, 405, { error: '请求方式不支持' });
    if (pathname === '/api/status') return sendJSON(response, 200, await publicationState());
    if (pathname === '/api/game-preview') return sendJSON(response, 200, await gamePreviewState());
    if (pathname === '/api/preview-textures') return sendJSON(response, 200, await previewTextures(url.searchParams.get('build_id') || '', Number(url.searchParams.get('max_size'))));
    if (pathname === '/api/preview-diagnostics') return sendJSON(response, 200, await readJSON(diagnosticsFile, { phase: 'not_reported' }));
    if (pathname === '/api/identity') return sendJSON(response, 200, identity);
    if (pathname === '/api/config') {
      const config = await readJSON(path.join(ROOT, 'config/project.json'), {});
      return sendJSON(response, 200, { preview: config.preview || {}, dimensions: config.dimensions_m || config.dimensions || config.court_dimensions || {} });
    }
    if (pathname === '/events') {
      const currentState = await publicationState();
      response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache, no-transform', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' });
      response.write(`data: ${JSON.stringify({ type: 'connection_state', ...currentState })}\n\n`);
      clients.add(response);
      request.on('close', () => clients.delete(response));
      return;
    }
    if (pathname === '/favicon.ico') { response.writeHead(204); return response.end(); }
    if (pathname.startsWith('/builds/')) return sendFile(request, response, path.join(ROOT, 'public/builds'), pathname.slice('/builds/'.length), true);
    if (pathname.startsWith('/game-preview/')) return sendFile(request, response, path.join(ROOT, 'public/game-preview'), pathname.slice('/game-preview/'.length));
    if (pathname.startsWith('/preview-textures/')) return sendFile(request, response, textureCacheRoot, pathname.slice('/preview-textures/'.length), true);
    if (pathname === '/manifest.json') return sendFile(request, response, path.join(ROOT, 'public'), 'manifest.json');
    if (pathname.startsWith('/references/')) return sendFile(request, response, path.join(ROOT, 'public/references'), pathname.slice('/references/'.length));
    if (pathname.startsWith('/logs/') && /^[a-zA-Z0-9_.-]+\.log$/.test(pathname.slice(6))) return sendFile(request, response, path.join(ROOT, 'logs'), pathname.slice(6));
    return sendFile(request, response, path.join(ROOT, 'preview'), pathname === '/' ? 'index.html' : pathname.slice(1));
  } catch (error) { sendJSON(response, 500, { error: error.message }); }
});

watcher.on('event', event => {
  const message = `data: ${JSON.stringify(event)}\n\n`;
  for (const client of clients) client.write(message);
  if (event.type === 'asset_build_started') console.log(`开始构建 ${event.build_id}`);
  if (event.type === 'asset_build_ready') console.log(`预览已就绪 ${event.manifest?.build_id}`);
  if (event.type === 'asset_build_failed') console.error(event.error);
});
const heartbeat = setInterval(() => { for (const client of clients) client.write(': heartbeat\n\n'); }, 15000);
server.on('error', async error => {
  if (error.code === 'EADDRINUSE') {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/identity`, { signal: AbortSignal.timeout(1500) });
      const status = await response.json();
      if (status.service === identity.service && status.project_root === identity.project_root) {
        console.log(`现有球场预览正在运行：http://127.0.0.1:${port}`);
        if (process.argv.includes('--open')) openBrowser(`http://127.0.0.1:${port}`);
        clearInterval(heartbeat); process.exit(0);
      }
    } catch {}
    console.error(`端口 ${port} 被其他程序占用。请修改 config/project.json 的 preview.port。`);
  } else console.error(error);
  clearInterval(heartbeat); process.exitCode = 1;
});
server.listen(port, '127.0.0.1', async () => {
  try {
    await fs.mkdir(runtimeDirectory, { recursive: true });
    const tempState = `${stateFile}.${identity.instance_id}.tmp`;
    await fs.writeFile(tempState, JSON.stringify({ ...identity, control_token: controlToken }, null, 2));
    await fs.rename(tempState, stateFile);
  } catch (error) {
    console.error(`无法保存本项目的服务控制信息：${error.message}`);
    return stop();
  }
  console.log(`中关村大融城球场预览：http://127.0.0.1:${port}`);
  console.log('保存 source、artwork、config 内的文件会自动构建。Ctrl+C 停止。');
  await watcher.start().catch(error => watcher.watchError(error));
  if (process.argv.includes('--open')) openBrowser(`http://127.0.0.1:${port}`);
});
function stop() {
  if (stopping) return;
  stopping = true;
  watcher.stop();
  clearInterval(heartbeat);
  for (const client of clients) client.end();
  const forcedClose = setTimeout(() => server.closeAllConnections(), 1500);
  server.close(async () => {
    clearTimeout(forcedClose);
    try {
      const savedState = await readJSON(stateFile);
      if (savedState?.instance_id === identity.instance_id) await fs.unlink(stateFile);
    } catch (error) { console.error(`服务已停止；控制信息清理失败：${error.message}`); }
    process.exit();
  });
}
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
