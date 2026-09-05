from pathlib import Path
from core.scanner import Repository
from core.engine import Analyzer
from core.ast import ASTAnalyzer
from core.deps import graph
from core.migrations import analyze as migration_analyze
from core.validate import static_dockerfile
from generators.docker import dockerfile
from generators.cloud import terraform,kubernetes
from pricing.engine import PricingEngine
from security.audit import audit
from sandbox.runner import diagnose

def fixture(tmp_path):
 (tmp_path/'package.json').write_text('{"scripts":{"build":"npm run build","start":"node dist/server.js"},"dependencies":{"express":"4.0.0","pg":"8.0.0"}}');(tmp_path/'package-lock.json').write_text('{"packages":{"":{"dependencies":{"express":"4.0.0"}},"node_modules/express":{"version":"4.0.0","dependencies":{"accepts":"1.3.0"}},"node_modules/accepts":{"version":"1.3.0"}}}');(tmp_path/'tsconfig.json').write_text('{}');(tmp_path/'server.ts').write_text("import express from 'express';\nexport function health(){ return true }\n");(tmp_path/'migrations/001.sql').parent.mkdir();(tmp_path/'migrations/001.sql').write_text('ALTER TABLE users ADD COLUMN name text;\nDROP TABLE legacy;\n');return Repository(tmp_path)
def test_detection_and_ast(tmp_path):
 r=fixture(tmp_path);spec,_,out=Analyzer(r).analyze();assert spec.runtime['name']=='Node.js';assert out['summary']['framework']=='Express';a=ASTAnalyzer(r).analyze();assert any(x['module']=='express' for x in a['imports'])
def test_dependency_graph_and_migrations(tmp_path):
 r=fixture(tmp_path);g=graph(r);assert g['resolved_count']>=2;m=migration_analyze(r);assert m['requires_manual_approval'];assert any(x['code']=='DROP_TABLE' for x in m['destructive_changes'])
def test_security_and_validation():
 class R:
  files=['.env','Dockerfile'];text={'.env':'TOKEN=supersecretvalue123','Dockerfile':'FROM python:latest\nARG API_KEY=bad\nUSER root'}
  def read(self,f,limit=250000):return self.text.get(f,'')
 assert len(audit(R()))>=3;assert not static_dockerfile('FROM python:latest\nUSER root')['valid']
def test_generators_and_pricing(tmp_path):
 r=fixture(tmp_path);spec,_,_=Analyzer(r).analyze();spec.services=[{'name':'PostgreSQL'}];assert 'USER 10001' in dockerfile(spec);assert 'aws_ecs_cluster' in terraform(spec,'aws');assert 'Deployment' in kubernetes(spec);assert PricingEngine().estimate(spec,'aws')['estimated_monthly_usd']>0
def test_diagnosis():
 assert diagnose('Cannot find module express')['code']=='missing_module';assert diagnose('permission denied /app/app')['code']=='permission'
def test_migration_detector_source_cannot_flag_itself(tmp_path):
 (tmp_path/'requirements.txt').write_text('fastapi\n');(tmp_path/'app/migrations.py').parent.mkdir();(tmp_path/'app/migrations.py').write_text("FRAMEWORKS=[('Django','migrations/')]\nDESTRUCTIVE=[('DB_DESTROY',r'destroy_all')]\n")
 m=migration_analyze(Repository(tmp_path));assert m['systems']==[];assert not m['requires_manual_approval'];assert m['destructive_changes']==[]
