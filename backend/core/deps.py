from pathlib import Path
import re

def _node(repo):
    nodes=[];edges=[];j=repo.json('package.json')
    for typ in ('dependencies','devDependencies','optionalDependencies','peerDependencies'):
        for name,ver in j.get(typ,{}).items():nodes.append({'id':f'npm:{name}','name':name,'version':ver,'kind':typ,'ecosystem':'npm'})
    if 'package-lock.json' in repo.file_set:
        for path,data in repo.json('package-lock.json').get('packages',{}).items():
            if not path.startswith('node_modules/'):continue
            name=path.split('node_modules/')[-1];nid=f'npm:{name}'
            if not any(x['id']==nid and x.get('kind')!='resolved' for x in nodes):nodes.append({'id':nid,'name':name,'version':data.get('version'),'kind':'resolved','ecosystem':'npm'})
            for dep in data.get('dependencies',{}):edges.append({'from':nid,'to':f'npm:{dep}','kind':'runtime'})
    return nodes,edges

def _requirements(repo):
    nodes=[]
    for f in ('requirements.txt','requirements/base.txt','requirements/prod.txt'):
        if f not in repo.file_set:continue
        for line in repo.read(f).splitlines():
            s=line.strip()
            if not s or s.startswith('#') or s.startswith('-r'):continue
            name=re.split(r'[<>=!~;\[]',s)[0].strip()
            if name:nodes.append({'id':f'pypi:{name.lower()}','name':name,'version':s,'kind':'direct','ecosystem':'pypi'})
    return nodes,[]

def _go(repo):
    nodes=[]
    if 'go.mod' not in repo.file_set:return nodes,[]
    for m in re.finditer(r'^\s*([\w./-]+)\s+v([^\s]+)',repo.read('go.mod'),re.M):nodes.append({'id':f'go:{m.group(1)}','name':m.group(1),'version':m.group(2),'kind':'direct','ecosystem':'go'})
    if 'go.sum' in repo.file_set:
        for m in re.finditer(r'^([^\s]+)\s+v([^\s]+)\s+[^\s]+$',repo.read('go.sum'),re.M):
            if not any(x['id']==f'go:{m.group(1)}' for x in nodes):nodes.append({'id':f'go:{m.group(1)}','name':m.group(1),'version':m.group(2),'kind':'resolved','ecosystem':'go'})
    return nodes,[]

def _cargo(repo):
    nodes=[];txt=repo.read('Cargo.toml') if 'Cargo.toml' in repo.file_set else '';active=False
    for line in txt.splitlines():
        if line.strip().startswith('['):active=line.strip() in {'[dependencies]','[dev-dependencies]','[build-dependencies]'};continue
        if active and re.match(r'^\s*[\w-]+\s*=\s*',line):nodes.append({'id':f"cargo:{line.split('=',1)[0].strip()}",'name':line.split('=',1)[0].strip(),'version':line.split('=',1)[1].strip(),'kind':'direct','ecosystem':'cargo'})
    return nodes,[]

def graph(repo):
    nodes=[];edges=[]
    for fn in (_node,_requirements,_go,_cargo):n,e=fn(repo);nodes.extend(n);edges.extend(e)
    if 'pyproject.toml' in repo.file_set:
        for m in re.finditer(r'^\s*[\"\']?([A-Za-z0-9_.-]+)[\"\']?\s*=\s*[\"\']([^\"\']+)',repo.read('pyproject.toml'),re.M):
            n,v=m.groups()
            if n.lower() not in {'requires-python','version','description'}:nodes.append({'id':f'pypi:{n.lower()}','name':n,'version':v,'kind':'manifest','ecosystem':'pypi'})
    if 'pom.xml' in repo.file_set:
        for m in re.finditer(r'<dependency>.*?<groupId>(.*?)</groupId>.*?<artifactId>(.*?)</artifactId>.*?(?:<version>(.*?)</version>)?.*?</dependency>',repo.read('pom.xml'),re.S):nodes.append({'id':f'maven:{m.group(1)}:{m.group(2)}','name':f'{m.group(1)}:{m.group(2)}','version':m.group(3) or 'managed','kind':'direct','ecosystem':'maven'})
    if 'composer.json' in repo.file_set:
        j=repo.json('composer.json')
        for typ in ('require','require-dev'):
            for n,v in j.get(typ,{}).items():nodes.append({'id':f'composer:{n}','name':n,'version':v,'kind':typ,'ecosystem':'composer'})
    if 'Gemfile' in repo.file_set:
        for m in re.finditer(r'^\s*gem\s+[\"\']([^\"\']+)[\"\'](?:,\s*[\"\']([^\"\']+))?',repo.read('Gemfile'),re.M):nodes.append({'id':f'gem:{m.group(1)}','name':m.group(1),'version':m.group(2) or 'unconstrained','kind':'direct','ecosystem':'bundler'})
    merged={};priority={'dependencies':5,'devDependencies':4,'optionalDependencies':4,'peerDependencies':4,'direct':5,'manifest':4,'resolved':2}
    for n in nodes:
        if n['id'] not in merged or priority.get(n.get('kind'),1)>priority.get(merged[n['id']].get('kind'),1):merged[n['id']]=n
    locks=[f for f in repo.files if Path(f).name in {'pnpm-lock.yaml','yarn.lock','bun.lock','poetry.lock','uv.lock','Pipfile.lock','Gemfile.lock','composer.lock','Cargo.lock','go.sum','package-lock.json'}]
    return {'nodes':list(merged.values()),'edges':edges,'direct_count':sum(n.get('kind') in {'dependencies','devDependencies','optionalDependencies','peerDependencies','direct','manifest'} for n in merged.values()),'resolved_count':sum(n.get('kind')=='resolved' for n in merged.values())+(len(merged) if locks else 0),'edge_count':len(edges),'lockfiles':locks,'complete':bool(locks) and bool(merged),'limitations':['Native package-manager resolution is required for mathematically complete transitive graphs for some lock formats.']}
