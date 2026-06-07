# saas/customers/

One YAML file per SaaS customer. The `saas-customer-namespaces` ApplicationSet reads
all files here and provisions a namespace for each customer on every saas-pooled cluster.

## File schema

```yaml
# saas/customers/<customer-slug>.yaml
customer: acme-corp          # org slug — used as namespace name and label value
customerTier: enterprise     # free | pro | enterprise — drives ResourceQuota size
namespace: acme-corp         # K8s namespace (usually same as customer slug)
```

## What gets created per customer per pooled cluster

- Namespace with required labels (model=saas-pooled, customer=<slug>, env, team)
- ResourceQuota sized to customerTier
- RBAC placeholder (ClusterRole binding for customer's admin group)

## Customer tiers → ResourceQuota

| Tier | CPU request | Memory request | CPU limit | Memory limit | Pods |
|---|---|---|---|---|---|
| free | 500m | 512Mi | 2 | 2Gi | 10 |
| pro | 2 | 2Gi | 8 | 8Gi | 50 |
| enterprise | 8 | 8Gi | 32 | 32Gi | 200 |

## SaaS-dedicated customers

For customers on dedicated clusters (model=saas-dedicated), do NOT add a file here.
Their cluster is provisioned via provision-workload.yml with model=saas-dedicated.
Their namespace is created by register-namespace.yml targeting their cluster.
