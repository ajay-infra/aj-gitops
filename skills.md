# skills.md — aj-platform-gitops

## Purpose
GitOps configuration repository for the ArgoCD hub. Defines all ApplicationSets, AppProjects, Helm chart values, and bootstrap Applications for every cluster tier.

## Type
`gitops-platform`

## Repo layout

```
applicationsets/
  central/nonprod/lgtm.yaml          — LGTM stack (Grafana/Loki/Mimir/Tempo) on central-nonprod
  central/prod/lgtm.yaml             — LGTM stack on central-prod
  workload/
    apps.yaml                        — team app workloads (git-file-generator × internal clusters)
    saas-customer-namespaces.yaml    — customer namespaces on saas-pooled clusters
    k8s-manifests.yaml               — OPA policies + Karpenter + KEDA + Kong (all workload clusters)
    k8s-monitoring.yaml              — Alloy + k8s-monitoring (all workload clusters)
    gatekeeper.yaml                  — OPA Gatekeeper controller
    keda.yaml                        — KEDA controller
    kong.yaml / kong-gateway.yaml    — Kong KIC + Gateway
    external-dns.yaml                — external-dns
    falcon.yaml                      — Falcon sensor DaemonSet
    cloudability.yaml                — Cloudability cost agent
    arc-controller.yaml              — Actions Runner Controller
    arc-runners.yaml                 — ephemeral runner pods
    gateway-api-crds.yaml            — Gateway API CRDs

bootstrap/
  nonprod.yaml                       — App-of-apps: bootstraps central-nonprod ApplicationSets
  prod.yaml                          — App-of-apps: bootstraps central-prod ApplicationSets

projects/
  platform.yaml                      — AppProject: infra-lead owned (LGTM, ArgoCD, platform tools)
  workloads.yaml                     — AppProject: team workload apps (per-team AppProjects created by workflow)

charts/                              — Helm values per env for all platform charts
  argocd/values/nonprod.yaml
  loki/values/, mimir/values/, etc.

teams/                               — One YAML per (team, app) — read by workload-apps ApplicationSet
  README.md
  <team>/<app>.yaml

saas/
  customers/                         — One YAML per SaaS customer — read by saas-customer-namespaces AppSet
    README.md
    <customer>.yaml
  namespace-template/                — Helm chart: namespace + ResourceQuota per customer
```

## Cluster model → ApplicationSet targeting

| Cluster label | Who deploys |
|---|---|
| `model: internal` | All workload AppSets + `workload-apps` (team git-file-generator) |
| `model: saas-pooled` | All workload AppSets + `saas-customer-namespaces` (customer namespace per customer YAML) |
| `model: saas-dedicated` | All workload AppSets + per-customer register-namespace.yml AppSets |

## Team onboarding (internal)

1. Add `teams/<team>/<app>.yaml` per service
2. Run `register-namespace.yml` to create AppProject
3. Merge → ArgoCD generates Applications automatically

## Customer onboarding (SaaS-pooled / UAT)

1. Add `saas/customers/<customer>.yaml`
2. Merge → ArgoCD provisions namespace + quota on all pooled clusters automatically

## Customer onboarding (SaaS-dedicated)

1. Provision cluster via `provision-workload.yml` with `model=saas-dedicated, customer=<slug>`
2. Run `register-namespace.yml` targeting that cluster

## Branching convention
- `main` — all ApplicationSets track `main`; PRs required for any change

## Agentic capabilities
- Detect clusters missing `model` label (not properly registered)
- Generate PR to add a new team app config to teams/
- Generate PR to add a new customer to saas/customers/
- Detect ApplicationSet drift (sync warnings, failed syncs)
- Weekly scan: list clusters by model breakdown
- Flip k8s-manifests enforcementAction warn→deny for a policy after compliance confirmed
