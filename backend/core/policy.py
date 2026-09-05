def deployment_gate(spec, static_validation, security_findings, validation):
    reasons=[]
    if spec.project.get('monorepo') and len(spec.processes)<1:reasons.append('Monorepo has no confidently identified runnable process.')
    if spec.policy.get('confidence',0)<80:reasons.append('Detection confidence below automatic deployment threshold.')
    if not static_validation.get('valid'):reasons.append('Generated container failed static security validation.')
    if spec.migrations.get('requires_manual_approval'):reasons.append('Destructive/ambiguous migration requires manual approval.')
    if any(f.get('severity') in {'critical','high'} for f in security_findings):reasons.append('High/critical security finding present.')
    if validation and validation.get('status')!='passed':reasons.append('Build/runtime validation did not pass.')
    return {'eligible':not reasons,'reasons':reasons,'required_approvals':['migration'] if spec.migrations.get('requires_manual_approval') else []}
