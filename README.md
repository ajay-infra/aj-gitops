# aj-platform-gitops

GitOps source of truth for the AI Search Engine platform layer.

Owns Helm values, ArgoCD bootstrap, ApplicationSets, and platform install workflows for all central and workload clusters.

---

## Contents

```
bootstrap/          one-time kubectl apply after ArgoCD is installed
charts/             Helm values files per component per environment
  argocd/           ArgoCD hub (central clusters only)
  grafana/          Grafana dashboard
  loki/             Log aggregation (S3-backed)
  mimir/            Long-term metrics storage (S3-backed)
  tempo/            Distributed tracing (S3-backed)
  k8s-monitoring/   Alloy collector on workload clusters
  argo-rollouts/    Pod-level canary/blue-green on workload clusters
applicationsets/
  central/          Installs LGTM stack on central clusters (via ArgoCD)
  workload/         Deploys k8s-monitoring + app workloads to all workload clusters
projects/           ArgoCD AppProject RBAC manifests
.github/workflows/
  bootstrap-argocd.yml      Install/upgrade ArgoCD via Helm
  install-argo-rollouts.yml Install/upgrade Argo Rollouts via Helm
  ci.yml                    Helm lint, YAML lint, schema validation
```

---

## How components are deployed

| Component | How | Managed by |
|---|---|---|
| ArgoCD | `bootstrap-argocd.yml` workflow (helm upgrade --install) | Workflow |
| Argo Rollouts | `install-argo-rollouts.yml` workflow (helm upgrade --install) | Workflow |
| Grafana, Loki, Mimir, Tempo | ApplicationSet → ArgoCD Application | ArgoCD |
| k8s-monitoring (Alloy) | ApplicationSet → ArgoCD Application | ArgoCD |

ArgoCD and Argo Rollouts are intentionally kept outside ArgoCD's own management to avoid circular dependency and self-disruption during upgrades.

---

## Why central (umbrella) clusters do not use blue/green

Workload clusters (dev, staging, prod) use blue/green at the VPC level for zero-downtime upgrades. Central clusters do not. This is intentional.

### What central clusters host

- **ArgoCD hub** — manages all workload cluster syncs
- **Grafana LGTM** — receives metrics, logs, traces from every workload cluster

Both are critical platform services, which makes the upgrade question important.

### Why blue/green is not the right answer here

**1. What actually happens during an in-place EKS upgrade**

An EKS upgrade has two phases:

```
Phase 1 — Control plane upgrade (~10 minutes):
  The EKS API server is briefly unavailable.
  Pods on worker nodes KEEP RUNNING — data plane is unaffected.
  ArgoCD continues serving its existing synced state.
  Workload cluster agents reconnect automatically after API server returns.
  Alloy keeps buffering and shipping telemetry — no data loss.

Phase 2 — Node group rolling update (PDB-governed):
  EKS drains one node at a time.
  PodDisruptionBudgets prevent evicting the last replica of any component.
  ArgoCD (2 replicas prod) stays up — PDB ensures minAvailable=1 throughout.
  Loki/Mimir/Tempo (2+ replicas each) stay up — maxUnavailable=1.
  Effective downtime: zero, if HA is configured correctly.
```

**2. The cost argument**

Running two full LGTM stacks simultaneously during a blue/green cutover is expensive:

| Component | Prod replicas | Running two stacks |
|---|---|---|
| Mimir (distributed) | 10+ pods | 20+ pods |
| Loki (SimpleScalable) | 6 pods | 12 pods |
| Tempo | 1 pod | 2 pods |
| Grafana | 2 pods | 4 pods |
| ArgoCD | ~8 pods | ~16 pods |

All of this for a cluster that upgrades once or twice a year.

**3. ArgoCD state migration is risky**

With a blue/green central cluster swap, you would need to:
- Export every ArgoCD `Application`, `AppProject`, and cluster `Secret` from old central
- Re-register every workload cluster on the new central hub
- Re-apply every team's namespace onboarding (`register-namespace.yml`)
- Validate all syncs are healthy before decommissioning old central

This migration is far more operationally risky than an in-place rolling node replacement that respects PDBs.

**4. Upgrade frequency doesn't justify the overhead**

Blue/green pays for itself when you upgrade frequently (workload clusters: multiple times per year, each upgrade is routine). Central clusters: once a year for EKS version, rarely otherwise. The operational overhead of maintaining B/G infrastructure for a once-a-year event doesn't make sense.

**5. ArgoCD and LGTM upgrades are already decoupled from EKS**

- ArgoCD upgrades: `bootstrap-argocd.yml` workflow — online Helm upgrade, rolling pod replacement
- LGTM upgrades: ApplicationSet version bump → ArgoCD does rolling Helm upgrade
- Neither requires an EKS node replacement

The EKS upgrade only affects the underlying node fleet, not the application layer.

### What makes in-place safe

The combination of three things removes meaningful downtime risk:

```
1. HA replicas
   ArgoCD server:       2 replicas (prod)
   ArgoCD repo-server:  2 replicas (prod)
   Loki write/read:     2 replicas each (prod)
   Mimir components:    2 replicas each (prod)

2. PodDisruptionBudgets on every multi-replica component
   Configured in charts/argocd/values/prod.yaml
   Configured in charts/loki/values/prod.yaml
   Configured in charts/mimir/values/prod.yaml
   Configured in charts/grafana/values/prod.yaml
   EKS node drain respects PDBs — will not evict if it would violate minAvailable

3. EKS managed node groups
   Roll nodes one at a time automatically
   Honor PDBs during draining
   Upgrade can be paused/resumed if issues arise
```

### Recommended upgrade procedure

```bash
# 1. Notify teams — central cluster maintenance window (30 min buffer)

# 2. Bump k8s_version in envs/central-<tier>/eks.tfvars

# 3. Run provision-central.yml — upgrades control plane (~10 min API blip)
#    Pods keep running, ArgoCD reconnects automatically

# 4. Run provision-central.yml again — rolls node groups (PDB-governed, ~15 min)
#    No pod downtime if HA + PDBs are in place

# 5. Verify ArgoCD is healthy
kubectl get pods -n argocd

# 6. Verify LGTM is healthy
kubectl get pods -n monitoring

# 7. If ArgoCD version bump also needed — run separately after EKS upgrade
#    bootstrap-argocd.yml action=upgrade
```

### When you might reconsider

Blue/green central becomes worth considering only if:
- Central clusters need to upgrade multiple times per month (not the case here)
- ArgoCD state is so large that migration tooling exists and is well-tested
- Multiple teams depend on sub-minute ArgoCD availability SLAs
- Regulatory requirements mandate zero-downtime for the management plane itself

None of these apply to this project at current scale.

---

## PDB reference

| Component | Values file | PDB config | Why |
|---|---|---|---|
| ArgoCD server (prod) | `charts/argocd/values/prod.yaml` | `minAvailable: 1` | UI + webhook triggers must stay up |
| ArgoCD repo-server (prod) | `charts/argocd/values/prod.yaml` | `minAvailable: 1` | Manifest rendering must stay up |
| ArgoCD applicationset (prod) | `charts/argocd/values/prod.yaml` | `minAvailable: 1` | ApplicationSet controller |
| ArgoCD controller (prod) | `charts/argocd/values/prod.yaml` | disabled | Single replica — PDB would block all drains |
| Grafana (prod) | `charts/grafana/values/prod.yaml` | `minAvailable: 1` | Dashboard availability |
| Loki write (prod) | `charts/loki/values/prod.yaml` | `maxUnavailable: 1` | Log ingestion continuity |
| Loki read (prod) | `charts/loki/values/prod.yaml` | `maxUnavailable: 1` | Log query continuity |
| Loki backend (prod) | `charts/loki/values/prod.yaml` | `maxUnavailable: 1` | Compaction + ruler |
| Mimir distributor (prod) | `charts/mimir/values/prod.yaml` | `maxUnavailable: 1` | Metric write path |
| Mimir ingester (prod) | `charts/mimir/values/prod.yaml` | `maxUnavailable: 1` | In-memory metric data |
| Mimir querier (prod) | `charts/mimir/values/prod.yaml` | `maxUnavailable: 1` | Metric read path |
| Mimir query-frontend (prod) | `charts/mimir/values/prod.yaml` | `maxUnavailable: 1` | Query fan-out |
| Mimir store-gateway (prod) | `charts/mimir/values/prod.yaml` | `maxUnavailable: 1` | S3 block serving |

Nonprod components run single replicas — PDBs disabled (would block all node drains for no HA benefit).
