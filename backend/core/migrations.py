from pathlib import Path
import re
FRAMEWORKS=[('Prisma','prisma/migrations'),('Alembic','alembic'),('Django','migrations/'),('Rails','db/migrate'),('Flyway','flyway'),('Liquibase','liquibase'),('EF Core','migration'),('TypeORM','migration'),('Knex','migrations')]
DESTRUCTIVE=[('DROP_TABLE',r'\bdrop\s+table\b'),('DROP_COLUMN',r'\bdrop\s+(?:column|index|constraint)\b'),('TRUNCATE',r'\btruncate\s+(?:table|schema)\b'),('DELETE_ALL',r'\bdelete\s+from\s+[\w."`]+\s*;?\s*$'),('ALTER_TYPE',r'\balter\s+table\b.*\balter\s+column\b.*\btype\b'),('NOT_NULL',r'\balter\s+table\b.*\bset\s+not\s+null\b'),('RENAME_AMBIGUOUS',r'\brename\s+(?:column|table)\b'),('DB_DESTROY',r'\b(?:dropdatabase|destroy_all|database\.drop)\b')]
ADDITIVE=[('CREATE_TABLE',r'\bcreate\s+table\b'),('ADD_COLUMN',r'\badd\s+column\b'),('CREATE_INDEX',r'\bcreate\s+(?:unique\s+)?index\b')]
def analyze(repo):
    files=[];systems=set();findings=[]
    for f in repo.files:
        lf=f.lower();text=repo.read(f)
        if any(x in lf for x in ('migration','migrations','alembic','db/migrate','flyway','liquibase')):files.append(f)
        for name,needle in FRAMEWORKS:
            if needle in lf or needle in text.lower():systems.add(name)
        if Path(f).suffix.lower() in {'.sql','.py','.js','.ts','.rb','.cs','.java','.kt','.php'} or 'migration' in lf:
            for code,pat in DESTRUCTIVE:
                for m in re.finditer(pat,text,re.I|re.M):findings.append({'code':code,'severity':'critical' if code in {'DROP_TABLE','TRUNCATE','DB_DESTROY'} else 'high','file':f,'line':text.count('\n',0,m.start())+1,'message':f'Destructive migration operation detected: {code}','manual_approval':True})
    rollback=any(any(k in repo.read(f).lower() for k in ('down(', 'rollback', 'revert', 'down_revision')) for f in files)
    return {'systems':sorted(systems),'migration_files':files[:2000],'destructive_changes':findings,'additive_change_signals':sum(1 for f in files for _,p in ADDITIVE if re.search(p,repo.read(f),re.I)),'rollback_evidence':rollback,'requires_manual_approval':bool(findings),'production_policy':'Destructive or ambiguous schema/data changes require explicit approval, backup/restore readiness and a rollback/expand-contract plan.','safe_auto_apply':not findings}
