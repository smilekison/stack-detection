from pathlib import Path
import re
from core.models import Finding
SECRET_PATTERNS=[('PRIVATE_KEY',r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),('AWS_ACCESS_KEY',r'\bAKIA[0-9A-Z]{16}\b'),('AWS_SECRET',r'(?i)aws_secret_access_key\s*[=:]\s*[A-Za-z0-9/+=]{30,}'),('JWT',r'\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\b'),('TOKEN_ASSIGNMENT',r'(?i)\b(api[_-]?key|secret|token|password|private[_-]?key)\s*[:=]\s*["\'][^"\']{12,}["\']')]
BAD_DOCKER=[('PRIVILEGED',r'(?im)^\s*(?:USER\s+root|--privileged)'),('SECRET_ARG',r'(?im)^\s*ARG\s+.*(?:TOKEN|SECRET|PASSWORD|KEY)'),('CURL_PIPE_SHELL',r'(?i)curl[^\n|]*\|\s*(?:sh|bash)'),('LATEST',r'(?im)^\s*FROM\s+[^\n:]+:latest')]
def audit(repo):
    out=[]
    for f in repo.files:
        text=repo.read(f,250000);base=Path(f).name
        if base.startswith('.env') and base not in {'.env.example','.env.sample','.env.template'}:out.append(Finding('high','SECRET_FILE','Secret-bearing environment file',f'{f} should not be committed or baked into an image.',f,1,'Remove, rotate exposed values and inject secrets at runtime.'))
        for code,pat in SECRET_PATTERNS:
            for m in re.finditer(pat,text):out.append(Finding('high','HARDCODED_SECRET',f'Potential {code}',f'Potential credential pattern detected in {f}.',f,text.count('\n',0,m.start())+1,'Remove and rotate the credential; use runtime secret injection.',0.82))
        if base.lower()=='dockerfile':
            for code,pat in BAD_DOCKER:
                if re.search(pat,text):out.append(Finding('high' if code!='LATEST' else 'medium',f'DOCKER_{code}',f'Unsafe Docker pattern: {code}',f'{f} contains {code}.',f,1,'Use immutable, least-privilege and secret-free image construction.'))
    return out
def sbom_plan(repo,package_manager,image='IMAGE_DIGEST'):
    return {'format':'CycloneDX JSON','commands':['syft dir:. -o cyclonedx-json > sbom.cdx.json',f'syft {image} -o cyclonedx-json > image-sbom.cdx.json'],'package_manager':package_manager,'gate':'SBOM must be generated from the exact artifact promoted.'}
def vulnerability_plan():return {'tool':'Trivy','commands':['trivy fs --scanners vuln,secret,misconfig --format json .','trivy image --scanners vuln,secret,misconfig --format json IMAGE_DIGEST'],'gates':{'critical':'fail','high':'policy-dependent','medium':'report','low':'report'}}
def policy(findings,sbom_available=False,vuln_available=False):
    critical=sum(1 for f in findings if getattr(f,'severity',None)=='critical');high=sum(1 for f in findings if getattr(f,'severity',None)=='high')
    return {'deployable':critical==0 and high==0 and sbom_available and vuln_available,'critical_findings':critical,'high_findings':high,'requires_approval':critical>0 or high>0,'sbom_required':True,'vulnerability_scan_required':True,'secret_scan_required':True}
