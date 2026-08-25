# CLAUDE.md — aj-platform-gitops

> Local context file for Claude. Not pushed to GitHub.

---

## What This Repo Does

GitOps source of truth for the central cluster platform layer and self-service team onboarding.

Two responsibilities:
1. **Platform components** — Helm values for ArgoCD, LGTM stack (Grafana/Loki/Mimir/Tempo), k8s-monitoring (Alloy), Argo Rollouts
2. **ApplicationSets** — installs LGTM on central clusters; deploys k8s-monitoring to all workload clusters

Does NOT contain team application manifests (those live in team repos).
Does NOT contain Terraform. Does NOT create ArgoCD Applications for team services (that's `aj-infra-release/register-namespace.yml`).

---

## Repo Layout

```
aj-platform-gitops/
├── bootstrap/
│   ├── nonprod.yaml         # kubectl apply once → ArgoCD picks up LGTM ApplicationSet
│   └── prod.yaml
├── projects/
│   ├── platform.yaml        # AppProject: ArgoCD, LGTM, k8s-monitoring, Argo Rollouts
│   └── workloads.yaml       # AppProject: catch-all for platform-managed app workloads
│                            # (team namespaces get their OWN AppProject via register-namespace.yml)
├── charts/
│   ├── argocd/values/
│   │   ├── nonprod.yaml     # argo/argo-cd: 1 replica, ksops, Rollouts UI extension, GitHub OIDC
│   │   └── prod.yaml        # argo/argo-cd: 2 replicas HA, Redis HA
│   ├── grafana/values/
│   │   ├── nonprod.yaml     # grafana/grafana: LGTM datasources wired, GitHub OAuth
│   │   └── prod.yaml        # grafana/grafana: 2 replicas, dashboards read-only
│   ├── loki/values/
│   │   ├── nonprod.yaml     # SingleBinary, 30d retention, S3
│   │   └── prod.yaml        # SimpleScalable 2+2+2, 90d retention, S3
│   ├── mimir/values/
│   │   ├── nonprod.yaml     # single-binary mode, 90d retention
│   │   └── prod.yaml        # read-write microservices, 365d retention
│   ├── tempo/values/
│   │   ├── nonprod.yaml     # single binary, 14d, metricsGenerator→Mimir
│   │   └── prod.yaml        # single binary, 30d
│   ├── k8s-monitoring/values/
│   │   ├── dev.yaml         # grafana/k8s-monitoring → central-nonprod endpoints
│   │   ├── staging.yaml     # grafana/k8s-monitoring → central-nonprod endpoints
│   │   └── prod.yaml        # grafana/k8s-monitoring → central-prod endpoints
│   ├── argo-rollouts/values/
│   │   ├── dev.yaml         # 1 controller replica, dashboard enabled
│   │   ├── staging.yaml     # 1 controller replica, dashboard enabled
│   │   └── prod.yaml        # 2 controller replicas (HA), dashboard enabled
│   ├── arc-runners/values/{dev,staging,prod}.yaml    # GitHub Actions Runner Controller — runners
│   ├── cloudability/values/{dev,staging,prod}.yaml   # Apptio Cloudability cost-allocation agent
│   ├── external-dns/values/{dev,staging,prod-blue,prod-green}.yaml
│   ├── kong/values/{dev,staging,prod}.yaml           # Kong Ingress Controller
│   └── kong-gateway/         # Gateway API resources (Gateway, GatewayClass) — not Helm values
├── applicationsets/
│   ├── central/
│   │   ├── nonprod/
│   │   │   └── lgtm.yaml    # List: grafana+loki+mimir+tempo on central-nonprod
│   │   └── prod/
│   │       └── lgtm.yaml    # List: grafana+loki+mimir+tempo on central-prod (no auto-sync)
│   └── workload/
│       ├── k8s-monitoring.yaml  # Cluster generator: k8s-monitoring on every workload cluster
│       ├── apps.yaml            # Matrix: platform-managed app workloads (clusters × components)
│       ├── arc-runners.yaml, cloudability.yaml, external-dns.yaml, kong.yaml, kong-gateway.yaml,
│       │   gateway-api-crds.yaml, k8s-manifests.yaml, keda.yaml — all fully wired, values exist
│       └── arc-controller.yaml, gatekeeper.yaml, falcon.yaml — ⚠️ BROKEN, see Known Gaps below
└── .github/workflows/
    ├── ci.yml                   # helm lint, yamllint, kubeconform, helm template diff
    ├── bootstrap-argocd.yml     # helm install/upgrade ArgoCD on central clusters
    └── install-argo-rollouts.yml # helm install/upgrade Argo Rollouts on workload clusters
```

---

## How Platform Components Are Deployed

### ArgoCD (central clusters only)
**NOT managed by ArgoCD itself** — installed and upgraded via `bootstrap-argocd.yml` workflow.

```
workflow_dispatch: bootstrap-argocd.yml
  inputs: tier (nonprod/prod), action (install/upgrade)
  → helm upgrade --install argo-cd argo/argo-cd
  → kubectl apply -f bootstrap/<tier>.yaml   (install only)
```

To upgrade ArgoCD: bump `ARGOCD_CHART_VERSION` in `bootstrap-argocd.yml`, run with `action: upgrade`.

### LGTM Stack (central clusters only)
Managed by ArgoCD via ApplicationSet after bootstrap:
```
bootstrap/<tier>.yaml
  → ApplicationSet: applicationsets/central/<tier>/lgtm.yaml
    → Application: central-<tier>-grafana
    → Application: central-<tier>-loki
    → Application: central-<tier>-mimir
    → Application: central-<tier>-tempo
```
Each Application uses multi-source: upstream Helm chart + values files from this repo.

To upgrade a LGTM component: bump `version:` in the ApplicationSet → merge PR → ArgoCD auto-syncs (nonprod) or manual sync (prod).

### k8s-monitoring / Alloy (all workload clusters)
Deployed via ApplicationSet on each central cluster:
```
applicationsets/workload/k8s-monitoring.yaml
  cluster generator: tier=workload label → all registered workload clusters
  → Application: k8s-monitoring-<cluster-name>
     chart: grafana/k8s-monitoring (includes Alloy)
     values: charts/k8s-monitoring/values/<environment>.yaml
```
Ships metrics → central Mimir, logs → central Loki, traces → central Tempo over VPC peering.

### Argo Rollouts (workload clusters)
**NOT managed by ArgoCD** — installed and upgraded via `install-argo-rollouts.yml` workflow (same reasoning as ArgoCD).

```
workflow_dispatch: install-argo-rollouts.yml
  inputs: environment, color (prod only), action (install/upgrade)
  → helm upgrade --install argo-rollouts argo/argo-rollouts
```

To upgrade: bump `ROLLOUTS_CHART_VERSION` in the workflow, run with `action: upgrade`.

---

## Helm Chart Versions (pinned)

| Chart | Version | Repo |
|---|---|---|
| `argo/argo-cd` | 7.7.11 | https://argoproj.github.io/argo-helm |
| `argo/argo-rollouts` | 2.38.0 | https://argoproj.github.io/argo-helm |
| `grafana/grafana` | 8.8.4 | https://grafana.github.io/helm-charts |
| `grafana/loki` | 6.24.0 | https://grafana.github.io/helm-charts |
| `grafana/mimir-distributed` | 5.5.1 | https://grafana.github.io/helm-charts |
| `grafana/tempo` | 1.14.0 | https://grafana.github.io/helm-charts |
| `grafana/k8s-monitoring` | 2.0.2 | https://grafana.github.io/helm-charts |

---

## AppProject Design

| Project | Owns | Who can sync |
|---|---|---|
| `platform` | ArgoCD, LGTM, k8s-monitoring, Argo Rollouts | `infra-lead` only |
| `workloads` | Platform-managed app workloads (from `apps.yaml` ApplicationSet) | `infra-core` + `engineers` (dev/staging), `infra-lead` (prod) |
| `<namespace>` | Team-specific apps created by `register-namespace.yml` | `ajay-infra/<team>` GitHub team |

Team namespaces get their **own AppProject** (not `workloads`) via `aj-infra-release/register-namespace.yml`.
This scopes them to their namespace only and gives their GitHub team sync access in the ArgoCD UI.

---

## Cluster Secret Labels (used by ApplicationSet generators)

The `argocd-register` stage in `provision-eks.yml` creates a cluster Secret in `argocd` namespace.
ApplicationSet generators filter on these labels:

```yaml
labels:
  tier: workload          # picked up by k8s-monitoring.yaml + apps.yaml
  environment: dev        # maps to k8s-monitoring values file
  auto_sync: "true"       # dev + staging: "true"; prod: "false"
```

---

## Bootstrap Sequence (first time)

```
1. provision-central.yml  → central EKS cluster up
2. bootstrap-argocd.yml (action: install)
     → helm install ArgoCD
     → kubectl apply projects/platform.yaml
     → kubectl apply projects/workloads.yaml
     → kubectl apply bootstrap/<tier>.yaml
3. ArgoCD syncs lgtm.yaml → installs Grafana + Loki + Mimir + Tempo
4. provision-eks.yml      → workload cluster up + registered with ArgoCD
5. install-argo-rollouts.yml → Argo Rollouts on workload cluster
6. ArgoCD syncs k8s-monitoring ApplicationSet → deploys to new workload cluster
7. register-namespace.yml (aj-infra-release) → team onboarded
```

---

## Values File Pattern

No wrapper `Chart.yaml` in this repo. ArgoCD Applications use multi-source:
- **Source 1**: upstream Helm chart at pinned version
- **Source 2**: this repo (`ref: values`) for values files referenced as `$values/charts/<component>/values/<env>.yaml`

`charts/` contains only `values/<env>.yaml` files — no `Chart.yaml`, no `templates/`.

---

## S3 Bucket Names

Loki, Mimir, and Tempo S3 bucket names are injected at deploy time (Terraform outputs).
They are NOT hardcoded in values files. Set via ApplicationSet `parameters:` or ESO-synced ConfigMap.

| Component | Helm key |
|---|---|
| Loki | `loki.storage.s3.bucketnames` |
| Mimir | `mimir.structuredConfig.common.storage.s3.bucket_name` |
| Tempo | `tempo.storage.trace.s3.bucket` |

---

## Known Gaps

**Three workload ApplicationSets reference chart values files that don't exist —
confirmed by directory listing, not just a doc claim:**

| ApplicationSet | References | Exists? |
|---|---|---|
| `applicationsets/workload/arc-controller.yaml` | `$values/charts/arc-controller/values/{{env}}.yaml` | ❌ no `charts/arc-controller/` dir at all |
| `applicationsets/workload/gatekeeper.yaml` | `$values/charts/gatekeeper/values/{{env}}.yaml` | ❌ no `charts/gatekeeper/` dir at all |
| `applicationsets/workload/falcon.yaml` | `$values/charts/falcon/values/{{env}}.yaml` | ❌ no `charts/falcon/` dir at all |

All three ApplicationSets use the `tier: workload` cluster generator — same as the
working ones (`arc-runners`, `cloudability`, `external-dns`, `kong`, `keda`) — so
they are live, not disabled or dormant. If ArgoCD tries to sync any of these against
a registered workload cluster, the Helm `valueFiles` source will fail to resolve and
the Application will go into a permanent sync error, not silently skip.

This was not caught before because no workload cluster has been registered with
ArgoCD yet (per `aj-infra-context`'s roadmap) — nothing has actually tried to sync
these three ApplicationSets in practice. Before the first real cluster registration,
either add the missing `charts/<name>/values/<env>.yaml` files (real Helm values,
not fabricated ones — needs actual Gatekeeper/Falcon/ARC-controller config decisions)
or remove/disable these three ApplicationSets until that work is done.

**`onboard-saas-customer` (in `aj-agent-farm`, marked "implemented" in the farm's
skills catalog) has no matching infrastructure here.** The skill's `generate.py`
writes to `saas/customers/<customer>.yaml` and its `skill.md` says "The
`saas-customer-namespaces` ApplicationSet watches `saas/customers/*.yaml`" — grepped
this entire repo for "saas" (case-insensitive, all file types): zero matches. No
`saas/` directory, no `saas-customer-namespaces` ApplicationSet, nothing. If this
skill is run today, the PR would merge cleanly and report success, but the generated
file would sit unwatched — no ArgoCD Application would ever be created for the
customer, and nobody would notice from the PR/skill output alone.

## ksops (SOPS Decryption in ArgoCD)

ArgoCD repo-server runs the ksops plugin (initContainer install).
AGE private key stored in AWS Secrets Manager → synced via ESO as `sops-age-key` Secret before bootstrap.

Encrypt new secrets:
```bash
sops --encrypt --age $(cat .sops-recipients) secret.yaml > secret.enc.yaml
```
