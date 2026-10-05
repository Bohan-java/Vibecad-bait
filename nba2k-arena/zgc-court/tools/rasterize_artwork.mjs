import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const config = JSON.parse(await readFile(path.join(root, 'config/project.json'), 'utf8'));
const require = createRequire(import.meta.url);
const sharp = require(config.tools.sharp_module);
await mkdir(path.join(root, 'artwork'), { recursive: true });
const courtSVG = await readFile(path.join(root,'artwork/court.svg'),'utf8');
// Geometry and all paint shapes come exclusively from the editable SVG. The
// deterministic pixel finish only adds sub-centimetre mineral grain; it neither
// replaces artwork nor projects a reference photo onto the surface.
async function renderSurface(svg,destination,width,uniformOuterEdge=false){
const {data,info}=await sharp(Buffer.from(svg),{density:uniformOuterEdge?8192/5600*72:144})
  .resize({width}).removeAlpha().raw().toBuffer({resolveWithObject:true});
let seed=20261003;
const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
for(let y=0;y<info.height;y++){
  for(let x=0;x<info.width;x++){
    const i=(y*info.width+x)*info.channels;
    const n=(random()+random()+random()-1.5)*3.0;
    const pore=random()<0.018 ? -4.3-random()*7.5 : 0;
    const broad=.8*Math.sin(x*.032+y*.013)+.6*Math.sin(x*.007-y*.019);
    const edgeDistance=Math.min(x,y,info.width-1-x,info.height-1-y);
    const finish=uniformOuterEdge?Math.min(1,Math.max(0,(edgeDistance-32)/64)):1;
    // Force a truly uniform guard band; fractional SVG viewBox boundaries can
    // otherwise leave one antialiased pixel on the left or right outer edge.
    if(uniformOuterEdge&&edgeDistance<=32){data[i]=148;data[i+1]=153;data[i+2]=148;continue;}
    for(let c=0;c<3;c++)data[i+c]=Math.max(0,Math.min(255,Math.round(data[i+c]+(n+pore+broad)*finish)));
  }
}
const temporary=destination+'.'+process.pid+'.tmp';
await sharp(data,{raw:{width:info.width,height:info.height,channels:info.channels}}).png().toFile(temporary);
await rename(temporary, destination);
return {width:info.width,height:info.height};
}
await renderSurface(courtSVG,path.join(root,'artwork/court.png'),4096);
console.log('Updated editable court SVG texture: artwork/court.png');
// Embed the exact current court source at its original centimetre coordinates.
// Central paint is neither rescaled nor extended. Only the editable surrounding
// paving-context paths continue beyond the gameplay rectangle and apron.
const contextSVG=await readFile(path.join(root,'artwork/paving-context.svg'),'utf8');
const courtInner=courtSVG.replace(/^\s*<svg\b[^>]*>/,'').replace(/<\/svg>\s*$/,'');
const atlasSVG=contextSVG.replace(/<\/svg>\s*$/,`<svg xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" x="0" y="0" width="2865.12" height="1524" viewBox="0 0 2865.12 1524" overflow="hidden">${courtInner}</svg>\n</svg>\n`);
const atlasSource=path.join(root,'artwork/paving-atlas.svg');
const atlasTemporary=atlasSource+'.'+process.pid+'.tmp';
await writeFile(atlasTemporary,atlasSVG,'utf8');
await rename(atlasTemporary,atlasSource);
const atlas=await renderSurface(atlasSVG,path.join(root,'artwork/paving-atlas.png'),8192,true);
console.log(`Updated shared world paving atlas: ${atlas.width}x${atlas.height}; central court.svg preserved at original scale`);
