from pathlib import Path
import tempfile
from main import detect, dockerfile_for, compose_for

def make_repo():
    root=Path(tempfile.mkdtemp())
    (root/'package.json').write_text('{"packageManager":"pnpm@9.15.0","scripts":{"build":"tsc","start":"node dist/server.js"},"dependencies":{"express":"5.0.0","pg":"1.0.0","redis":"1.0.0"}}')
    (root/'pnpm-lock.yaml').write_text('lockfileVersion: 9.0')
    (root/'tsconfig.json').write_text('{}')
    (root/'.nvmrc').write_text('20')
    (root/'server.ts').write_text("import express from 'express'; const app=express(); app.get('/health',(req,res)=>res.send('ok')); app.listen(process.env.PORT || 3000);")
    return root

def test_detect():
    d=detect(make_repo()); s=d['summary']
    assert s['language']=='TypeScript'; assert s['runtime']=='Node.js'; assert s['package_manager']=='pnpm'; assert s['package_manager_version']=='9.15.0'; assert s['framework']=='Express'; assert s['port']==3000; assert 'PostgreSQL' in s['services']; assert 'Redis' in s['services']; assert '/health' in s['health_endpoints']

def test_artifacts():
    d=detect(make_repo()); df=dockerfile_for(d); compose=compose_for(d)
    assert 'FROM node:20' in df; assert 'pnpm@9.15.0' in df; assert 'EXPOSE 3000' in df; assert 'postgres:16' in compose; assert 'redis:7-alpine' in compose
