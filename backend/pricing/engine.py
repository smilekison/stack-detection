from dataclasses import dataclass
from datetime import date
@dataclass(frozen=True)
class SKU: provider:str;region:str;name:str;unit_price:float;unit:str
CATALOG={'aws':{'compute':0.0416,'postgres':0.025,'redis':0.018,'storage':0.023,'egress':0.09,'lb':0.025,'nat':0.045,'logs':0.50},'gcp':{'compute':0.0400,'postgres':0.030,'redis':0.020,'storage':0.020,'egress':0.085,'lb':0.025,'nat':0.045,'logs':0.50},'azure':{'compute':0.042,'postgres':0.032,'redis':0.021,'storage':0.021,'egress':0.087,'lb':0.026,'nat':0.045,'logs':0.50}}
class PricingEngine:
 def __init__(self,catalog=None):self.catalog=catalog or CATALOG
 def estimate(self,spec,provider='aws',region='default',usage=None):
  usage=usage or {};c=self.catalog[provider];hours=usage.get('compute_hours',730);replicas=usage.get('replicas',1);storage=usage.get('storage_gb',20);egress=usage.get('egress_gb',0);logs=usage.get('logs_gb',0);services={x.get('name') for x in spec.services};items=[self._item('compute',replicas*c['compute']*hours,c['compute'],f'{replicas} replicas × {hours}h')]
  if 'PostgreSQL' in services:items.append(self._item('postgres',c['postgres']*hours,c['postgres'],'managed PostgreSQL hours'))
  if 'Redis' in services:items.append(self._item('redis',c['redis']*hours,c['redis'],'managed Redis hours'))
  if 'S3/Object Storage' in services:items.append(self._item('storage',storage*c['storage'],c['storage'],f'{storage} GB-month'))
  if replicas>0:items.append(self._item('lb',c['lb']*hours,c['lb'],'load balancer baseline'))
  if usage.get('nat_gb',0):items.append(self._item('nat',usage['nat_gb']*c['nat'],c['nat'],f"{usage['nat_gb']} GB NAT processing"))
  if egress:items.append(self._item('egress',egress*c['egress'],c['egress'],f'{egress} GB internet egress'))
  if logs:items.append(self._item('logs',logs*c['logs'],c['logs'],f'{logs} GB log ingestion'))
  total=round(sum(x['monthly_usd'] for x in items),2)
  return {'provider':provider,'region':region,'currency':'USD','catalog_version':'planning-2026-09','generated_on':str(date.today()),'assumptions':usage,'items':items,'estimated_monthly_usd':total,'estimated_annual_usd':round(total*12,2),'confidence':'planning','disclaimer':'Bundled catalog is not a live provider quote. Production billing should inject refreshed regional SKU data before commitment.'}
 def _item(self,sku,total,unit_price,basis):return {'sku':sku,'quantity_basis':basis,'unit_price':unit_price,'monthly_usd':round(total,2)}
def estimate(spec,provider='aws',replicas=1,storage_gb=20,region='default'):return PricingEngine().estimate(spec,provider,region,{'replicas':replicas,'storage_gb':storage_gb})
