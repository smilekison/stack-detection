from dataclasses import dataclass,asdict
@dataclass(frozen=True)
class SandboxPolicy:
 build_timeout_seconds:int=900;runtime_timeout_seconds:int=60;memory_mb:int=1024;cpus:float=1.0;pids_limit:int=128;runtime_network:str='none';build_network:str='controlled-egress';drop_all_capabilities:bool=True;no_new_privileges:bool=True;read_only_rootfs:bool=True;non_root_required:bool=True;host_mounts:tuple=();cloud_credentials:bool=False;docker_socket_exposed_to_api:bool=False;max_output_bytes:int=2000000;max_repair_attempts:int=5
 def to_dict(self):return asdict(self)
DEFAULT_POLICY=SandboxPolicy()
def validate_policy(policy=DEFAULT_POLICY):
 errors=[]
 if policy.runtime_network!='none':errors.append('Runtime network must be none.')
 if policy.cloud_credentials:errors.append('Cloud credentials must never enter an untrusted build/runtime container.')
 if policy.host_mounts:errors.append('Host mounts are forbidden for untrusted workloads.')
 if not policy.drop_all_capabilities:errors.append('All Linux capabilities must be dropped.')
 if not policy.no_new_privileges:errors.append('no-new-privileges is mandatory.')
 if not policy.non_root_required:errors.append('Non-root runtime is mandatory.')
 return {'valid':not errors,'errors':errors,'policy':policy.to_dict()}
