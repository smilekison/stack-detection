import re

def _common(spec):
    port=spec.network.get('port') or 8000;health=spec.network.get('health_endpoint') or '/';name=re.sub(r'[^a-z0-9-]','-',spec.project.get('name','app').lower())[:40];return name,port,health

def terraform(spec,provider):
    name,port,health=_common(spec);services={x.get('name') for x in spec.services};db='PostgreSQL' in services;redis='Redis' in services
    if provider=='aws':
        dbres='''resource "aws_db_instance" "postgres" { count=var.enable_postgres engine="postgres" instance_class=var.db_instance_class allocated_storage=20 db_name="app" username="app" manage_master_user_password=true skip_final_snapshot=false deletion_protection=true multi_az=var.multi_az }''' if db else ''
        cres='''resource "aws_elasticache_replication_group" "redis" { count=var.enable_redis replication_group_id="app-redis" description="Redis for app" node_type=var.redis_node_type num_cache_clusters=1 automatic_failover_enabled=false }''' if redis else ''
        return f'''terraform {{ required_version=">=1.8.0" required_providers {{ aws={{source="hashicorp/aws" version="~>6.0"}} }} }}
provider "aws" {{ region=var.region }}
variable "region" {{type=string default="us-east-1"}}
variable "container_image" {{type=string}}
variable "desired_count" {{type=number default=2}}
variable "cpu" {{type=number default=512}}
variable "memory" {{type=number default=1024}}
variable "enable_postgres" {{type=bool default={str(db).lower()}}}
variable "enable_redis" {{type=bool default={str(redis).lower()}}}
variable "db_instance_class" {{type=string default="db.t4g.micro"}}
variable "redis_node_type" {{type=string default="cache.t4g.micro"}}
variable "multi_az" {{type=bool default=false}}
resource "aws_vpc" "app" {{cidr_block="10.40.0.0/16" enable_dns_hostnames=true enable_dns_support=true}}
resource "aws_subnet" "public_a" {{vpc_id=aws_vpc.app.id cidr_block="10.40.1.0/24" availability_zone="${{var.region}}a"}}
resource "aws_subnet" "public_b" {{vpc_id=aws_vpc.app.id cidr_block="10.40.2.0/24" availability_zone="${{var.region}}b"}}
resource "aws_security_group" "app" {{name="{name}-app" vpc_id=aws_vpc.app.id ingress {{from_port={port} to_port={port} protocol="tcp" cidr_blocks=["0.0.0.0/0"]}} egress {{from_port=0 to_port=0 protocol="-1" cidr_blocks=["0.0.0.0/0"]}}}}
resource "aws_ecs_cluster" "app" {{name="{name}"}}
resource "aws_iam_role" "ecs_execution" {{name="{name}-execution" assume_role_policy=jsonencode({{Version="2012-10-17",Statement=[{{Effect="Allow",Principal={{Service="ecs-tasks.amazonaws.com"}},Action="sts:AssumeRole"}}]}})}}
resource "aws_iam_role_policy_attachment" "ecs_execution" {{role=aws_iam_role.ecs_execution.name policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"}}
resource "aws_iam_role" "ecs_task" {{name="{name}-task" assume_role_policy=jsonencode({{Version="2012-10-17",Statement=[{{Effect="Allow",Principal={{Service="ecs-tasks.amazonaws.com"}},Action="sts:AssumeRole"}}]}})}}
resource "aws_cloudwatch_log_group" "app" {{name="/ecs/{name}" retention_in_days=30}}
resource "aws_ecs_task_definition" "app" {{family="{name}" requires_compatibilities=["FARGATE"] network_mode="awsvpc" cpu=tostring(var.cpu) memory=tostring(var.memory) execution_role_arn=aws_iam_role.ecs_execution.arn task_role_arn=aws_iam_role.ecs_task.arn container_definitions=jsonencode([{{name="app" image=var.container_image essential=true cpu=var.cpu memory=var.memory portMappings=[{{containerPort={port}}}] logConfiguration={{logDriver="awslogs" options={{awslogs-group=aws_cloudwatch_log_group.app.name awslogs-region=var.region awslogs-stream-prefix="app"}}}}}}])}}
resource "aws_ecs_service" "app" {{name="{name}" cluster=aws_ecs_cluster.app.id task_definition=aws_ecs_task_definition.app.arn desired_count=var.desired_count launch_type="FARGATE" network_configuration={{subnets=[aws_subnet.public_a.id,aws_subnet.public_b.id],security_groups=[aws_security_group.app.id],assign_public_ip=true}}}}
{dbres}
{cres}
output "service" {{value=aws_ecs_service.app.name}}
'''
    if provider=='gcp':
        dbres='''resource "google_sql_database_instance" "postgres" { database_version="POSTGRES_17" region=var.region settings { tier="db-custom-1-3840" availability_type="ZONAL" backup_configuration { enabled=true } } deletion_protection=true }''' if db else ''
        cres='''resource "google_redis_instance" "redis" { name="app-redis" tier="BASIC" memory_size_gb=1 region=var.region }''' if redis else ''
        return f'''terraform {{required_providers {{google={{source="hashicorp/google" version="~>7.0"}}}}}}
provider "google" {{project=var.project region=var.region}}
variable "project" {{type=string}}
variable "region" {{type=string default="us-central1"}}
variable "container_image" {{type=string}}
resource "google_cloud_run_v2_service" "app" {{name="{name}" location=var.region deletion_protection=true template {{containers {{image=var.container_image ports {{container_port={port}}} resources {{limits={{cpu="1" memory="1Gi"}}}}}} scaling {{min_instance_count=1 max_instance_count=10}}}}}}
resource "google_cloud_run_v2_service_iam_member" "public" {{name=google_cloud_run_v2_service.app.name location=var.region role="roles/run.invoker" member="allUsers"}}
{dbres}
{cres}
'''
    dbres='''resource "azurerm_postgresql_flexible_server" "postgres" { name="app-postgres" resource_group_name=azurerm_resource_group.app.name location=azurerm_resource_group.app.location version="16" sku_name="B_Standard_B1ms" storage_mb=32768 backup_retention_days=7 }''' if db else ''
    cres='''resource "azurerm_redis_cache" "redis" { name="app-redis" location=azurerm_resource_group.app.location resource_group_name=azurerm_resource_group.app.name capacity=0 family="C" sku_name="Basic" minimum_tls_version="1.2" }''' if redis else ''
    return f'''terraform {{required_providers {{azurerm={{source="hashicorp/azurerm" version="~>4.0"}}}}}}
provider "azurerm" {{features {{}}}}
variable "location" {{type=string default="West Europe"}}
variable "container_image" {{type=string}}
resource "azurerm_resource_group" "app" {{name="{name}-rg" location=var.location}}
resource "azurerm_container_app_environment" "app" {{name="{name}-env" location=azurerm_resource_group.app.location resource_group_name=azurerm_resource_group.app.name}}
resource "azurerm_container_app" "app" {{name="{name}" container_app_environment_id=azurerm_container_app_environment.app.id revision_mode="Single" template {{container {{name="app" image=var.container_image cpu=1 memory="2Gi"}}}} ingress {{external_enabled=true target_port={port} transport="auto"}}}}
{dbres}
{cres}
'''

def kubernetes(spec):
    name,port,health=_common(spec);envs=spec.environment.get('names',[]);secret=[e for e in envs if e.upper().endswith(('PASSWORD','TOKEN','SECRET','KEY'))]
    env='\n'.join(f'            - name: {e}\n              valueFrom:\n                secretKeyRef:\n                  name: {name}-secrets\n                  key: {e}' for e in secret)
    return f'''apiVersion: v1
kind: Namespace
metadata: {{name: {name}}}
---
apiVersion: v1
kind: ServiceAccount
metadata: {{name: {name}, namespace: {name}}}
automountServiceAccountToken: false
---
apiVersion: apps/v1
kind: Deployment
metadata: {{name: {name}, namespace: {name}}}
spec:
  replicas: 2
  strategy: {{type: RollingUpdate}}
  selector: {{matchLabels: {{app: {name}}}}}
  template:
    metadata: {{labels: {{app: {name}}}}}
    spec:
      serviceAccountName: {name}
      automountServiceAccountToken: false
      securityContext: {{runAsNonRoot: true, seccompProfile: {{type: RuntimeDefault}}}}
      containers:
        - name: app
          image: REPLACE_WITH_DIGEST
          ports: [{{containerPort: {port}}}]
          env:
{env or '            []'}
          resources: {{requests: {{cpu: "250m", memory: "256Mi"}}, limits: {{cpu: "1", memory: "1Gi"}}}}
          securityContext: {{allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {{drop: [ALL]}}}}
          readinessProbe: {{httpGet: {{path: "{health}", port: {port}}}}}
          livenessProbe: {{httpGet: {{path: "{health}", port: {port}}}}}
---
apiVersion: v1
kind: Service
metadata: {{name: {name}, namespace: {name}}}
spec: {{selector: {{app: {name}}}, ports: [{{port: 80, targetPort: {port}}}]}}
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {{name: {name}, namespace: {name}}}
spec:
  scaleTargetRef: {{apiVersion: apps/v1, kind: Deployment, name: {name}}}
  minReplicas: 2
  maxReplicas: 10
  metrics: [{{type: Resource, resource: {{name: cpu, target: {{type: Utilization, averageUtilization: 70}}}}}}]
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata: {{name: {name}, namespace: {name}}}
spec: {{minAvailable: 1, selector: {{matchLabels: {{app: {name}}}}}}}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {{name: {name}-default-deny, namespace: {name}}}
spec: {{podSelector: {{}}, policyTypes: [Ingress, Egress], egress: []}}
'''
