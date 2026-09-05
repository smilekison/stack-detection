import re
from core.models import Finding

def static_dockerfile(text):
    fs=[]
    if not re.search(r'(?im)^\s*FROM\s+',text):fs.append(Finding('critical','DOCKER_NO_FROM','Dockerfile has no FROM instruction','A container image must declare a base image.'))
    if re.search(r'(?im)^\s*FROM\s+[^\n:]+:latest\b',text):fs.append(Finding('medium','DOCKER_MUTABLE_BASE','Mutable latest base image','Pin the base image to an immutable version or digest.'))
    if re.search(r'(?im)^\s*ARG\s+(?:.*)?(?:SECRET|TOKEN|PASSWORD|API_KEY)',text):fs.append(Finding('high','DOCKER_SECRET_ARG','Secret supplied as build ARG','Build args can persist in build metadata/layers.'))
    if re.search(r'(?im)^\s*COPY\s+\.\s+\.',text) and 'USER ' not in text:fs.append(Finding('medium','DOCKER_BROAD_COPY','Broad source copy without explicit runtime user','Use .dockerignore and a non-root runtime.'))
    if re.search(r'(?im)^\s*USER\s+root\b',text):fs.append(Finding('high','DOCKER_ROOT','Runtime executes as root','Create and use a dedicated non-root runtime user.'))
    if re.search(r'(?im)^\s*ADD\s+https?://',text):fs.append(Finding('high','DOCKER_REMOTE_ADD','Remote URL added directly to image','Download and verify artifacts during a controlled build step.'))
    return {'valid':not any(f.severity in {'critical','high'} for f in fs),'findings':[f.__dict__ for f in fs]}
