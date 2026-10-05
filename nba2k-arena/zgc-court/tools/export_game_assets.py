"""Decode the published, source-derived GLB into native-IFF builder inputs.

No invented proxy geometry: positions, split normals, UVs and materials come
from the actual exported asset. Game conversion is (Blender Y,Z,X)*100 cm.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import struct
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
DTYPES={5120:np.dtype('i1'),5121:np.dtype('u1'),5122:np.dtype('<i2'),5123:np.dtype('<u2'),5125:np.dtype('<u4'),5126:np.dtype('<f4')}
WIDTHS={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}
# glTF world (X,Y,Z) = Blender (X,Z,-Y); game = Blender (Y,Z,X).
TO_GAME=np.array([[0,0,-1],[0,1,0],[1,0,0]],float)

def load_glb(path):
    data=path.read_bytes()
    magic,version,total=struct.unpack_from('<4sII',data)
    assert magic==b'glTF' and version==2 and total==len(data)
    chunks={};offset=12
    while offset<len(data):
        size,kind=struct.unpack_from('<II',data,offset);offset+=8
        chunks[kind]=data[offset:offset+size];offset+=size
    return json.loads(chunks[0x4e4f534a]),chunks[0x004e4942]

def accessor(doc,binary,index):
    spec=doc['accessors'][index]
    if 'sparse' in spec:raise ValueError('Sparse accessors need explicit expansion')
    view=doc['bufferViews'][spec['bufferView']];dtype=DTYPES[spec['componentType']]
    columns=WIDTHS[spec['type']];stride=view.get('byteStride',dtype.itemsize*columns)
    start=view.get('byteOffset',0)+spec.get('byteOffset',0)
    result=np.ndarray((spec['count'],columns),dtype=dtype,buffer=binary,offset=start,strides=(stride,dtype.itemsize)).copy()
    if spec.get('normalized'):
        limit=np.iinfo(dtype);result=result.astype(float)/limit.max
        if limit.min<0:result=np.maximum(result,-1)
    return result

def node_matrix(node):
    if 'matrix' in node:return np.array(node['matrix'],float).reshape(4,4,order='F')
    x,y,z,w=node.get('rotation',[0,0,0,1])
    rotation=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                       [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                       [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
    result=np.eye(4);result[:3,:3]=rotation@np.diag(node.get('scale',[1,1,1]));result[:3,3]=node.get('translation',[0,0,0])
    return result

def texture_info(doc,info,images):
    if info is None:return None
    texture=doc['textures'][info['index']]
    if 'source' not in texture:raise ValueError('Compressed-only texture is not supported by this adapter')
    transform=info.get('extensions',{}).get('KHR_texture_transform',{})
    return {'image':images[texture['source']],'texcoord':transform.get('texCoord',info.get('texCoord',0)),
            'offset':transform.get('offset',[0,0]),'scale':transform.get('scale',[1,1]),'rotation':transform.get('rotation',0),
            'sampler':doc.get('samplers',[])[texture['sampler']] if 'sampler' in texture else {}}

def split_primitive(indices,limit=60000):
    """Use full triangles and remap unique vertices; every native index is u16."""
    triangles=indices.reshape(-1,3)
    batch=[];used=set()
    for triangle in triangles:
        incoming=set(map(int,triangle))
        if len(used)+sum(v not in used for v in incoming)>limit and batch:
            values=np.array(batch,dtype=np.uint32).reshape(-1)
            unique,inverse=np.unique(values,return_inverse=True)
            yield unique,inverse.astype('<u2')
            batch=[];used=set()
        batch.append(triangle);used.update(incoming)
    if batch:
        values=np.array(batch,dtype=np.uint32).reshape(-1)
        unique,inverse=np.unique(values,return_inverse=True)
        yield unique,inverse.astype('<u2')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--glb');parser.add_argument('--output',default=str(ROOT/'.build-staging/iff/assets'))
    args=parser.parse_args();out=Path(args.output).resolve()
    if not out.is_relative_to(ROOT):raise ValueError('Output outside project')
    manifest=json.loads((ROOT/'public/manifest.json').read_text(encoding='utf8'))
    source=Path(args.glb).resolve() if args.glb else ROOT/'public'/manifest['model_url'].lstrip('/')
    doc,binary=load_glb(source);out.mkdir(parents=True,exist_ok=True);(out/'textures').mkdir(exist_ok=True);(out/'meshes').mkdir(exist_ok=True)
    images=[]
    for i,img in enumerate(doc.get('images',[])):
        if 'bufferView' not in img:raise ValueError('Require embedded GLB images')
        bv=doc['bufferViews'][img['bufferView']];start=bv.get('byteOffset',0)
        raw=binary[start:start+bv['byteLength']]
        suffix={'image/png':'.png','image/jpeg':'.jpg'}.get(img['mimeType'])
        if not suffix:raise ValueError('Unsupported source image '+img['mimeType'])
        name=f'textures/image-{i:04d}{suffix}';(out/name).write_bytes(raw)
        images.append({'file':name,'sha256':hashlib.sha256(raw).hexdigest(),'mime_type':img['mimeType']})
    materials=[]
    for i,mat in enumerate(doc.get('materials',[])):
        pbr=mat.get('pbrMetallicRoughness',{})
        materials.append({'id':i,'name':mat.get('name',f'material-{i}'),'base_color_linear':pbr.get('baseColorFactor',[1,1,1,1]),
            'roughness':pbr.get('roughnessFactor',1),'metallic':pbr.get('metallicFactor',1),'alpha_mode':mat.get('alphaMode','OPAQUE'),
            'alpha_cutoff':mat.get('alphaCutoff',.5),'double_sided':mat.get('doubleSided',False),
            'base_color_texture':texture_info(doc,pbr.get('baseColorTexture'),images),
            'metallic_roughness_texture':texture_info(doc,pbr.get('metallicRoughnessTexture'),images),
            'normal_texture':texture_info(doc,mat.get('normalTexture'),images),
            'extensions':mat.get('extensions',{})})
    parts=[];ignored=[]
    def visit(index,parent,ancestor_tags):
        node=doc['nodes'][index];matrix=parent@node_matrix(node)
        tags=ancestor_tags+[node.get('name',''),node.get('extras',{}).get('layer',''),node.get('extras',{}).get('category','')]
        if 'mesh' in node:
            if any(x in ('lights','preview_helpers') for x in tags):ignored.append(node.get('name'));return
            mesh=doc['meshes'][node['mesh']]
            for pidx,prim in enumerate(mesh['primitives']):
                if prim.get('mode',4)!=4:raise ValueError('Need triangle list')
                att=prim['attributes'];positions=accessor(doc,binary,att['POSITION']).astype(float)
                indices=accessor(doc,binary,prim['indices']).reshape(-1) if 'indices' in prim else np.arange(len(positions))
                if len(indices)%3:raise ValueError('Nontriangular index count')
                if 'NORMAL' not in att:raise ValueError('Missing exported split normals: '+str(node.get('name')))
                normals=accessor(doc,binary,att['NORMAL']).astype(float)
                normal_matrix=np.linalg.inv(matrix[:3,:3]).T
                positions=(positions@matrix[:3,:3].T+matrix[:3,3])@TO_GAME.T*100
                normals=normals@normal_matrix.T@TO_GAME.T;normals/=np.maximum(np.linalg.norm(normals,axis=1,keepdims=True),1e-12)
                if np.linalg.det(matrix[:3,:3])<0:indices=indices.reshape(-1,3)[:,[0,2,1]].reshape(-1)
                mid=prim.get('material',0);material=materials[mid]
                tex=material.get('base_color_texture') or material.get('metallic_roughness_texture') or material.get('normal_texture')
                uvkey=f'TEXCOORD_{tex["texcoord"] if tex else 0}'
                if tex and uvkey not in att:raise ValueError('Material texture is missing UVs: '+node.get('name',''))
                uv=accessor(doc,binary,att[uvkey]).astype(float) if uvkey in att else np.zeros((len(positions),2))
                if tex:
                    angle=tex['rotation'];c,s=np.cos(angle),np.sin(angle)
                    uv=(uv*np.array(tex['scale']))@np.array([[c,-s],[s,c]]).T+np.array(tex['offset'])
                for used,reindexed in split_primitive(indices):
                    number=len(parts);key=f'part-{number:04d}';filename=f'meshes/{key}.npz'
                    pos=positions[used].astype('<f4');norm=normals[used].astype('<f4');texuv=uv[used].astype('<f4')
                    if not all(np.isfinite(x).all() for x in (pos,norm,texuv)):raise ValueError('Nonfinite geometry')
                    np.savez(out/filename,position_cm=pos,normal=norm,uv=texuv,indices=reindexed)
                    parts.append({'key':key,'file':filename,'object':node.get('name',''),'primitive':pidx,'material':mid,
                        'tags':list(dict.fromkeys(str(t) for t in tags if t)),'vertices':len(used),'triangles':len(reindexed)//3,
                        'uv_source':uvkey,'min_cm':pos.min(0).tolist(),'max_cm':pos.max(0).tolist()})
        for child in node.get('children',[]):visit(child,matrix,tags)
    for node in doc['scenes'][doc.get('scene',0)]['nodes']:visit(node,np.eye(4),[])
    result={'schema':1,'source_glb':str(source),'source_glb_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'source_scene_extras':doc['scenes'][doc.get('scene',0)].get('extras',{}),'coordinate_system':'game centimetres: (Blender Y, Blender Z, Blender X)*100; right handed',
        'uv_convention':'glTF top-left image UV; material base texture KHR transform applied','materials':materials,'images':images,'parts':parts,'ignored_helpers':ignored,
        'totals':{'parts':len(parts),'vertices':sum(p['vertices'] for p in parts),'triangles':sum(p['triangles'] for p in parts)}}
    (out/'assets.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'output':str(out/'assets.json'),**result['totals']}))

if __name__=='__main__':main()
