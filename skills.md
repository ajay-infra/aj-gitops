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

## Golden-path Helm chart: `charts/web-service/`

Standard chart for any stateless web service on the platform. Teams reference it from their app's `helmPath:` in `teams/<team>/<app>.yaml`.

```
charts/web-service/
  Chart.yaml
  values.yaml             — full defaults; override per env via deployments/ and environments/<env>/
  templates/
    _helpers.tpl          — fullname, labels, selectorLabels
    deployment.yaml       — maxUnavailable=0 rolling, zone topology spread, pod anti-affinity,
                            terminationGracePeriodSeconds=30, drop-ALL securityContext,
                            conditional env/volumeMounts/volumes
    service.yaml          — ClusterIP + optional metrics port; konghq.com/protocol annotation
    pdb.yaml              — minAvailable configurable (1=dev, 2=prod via override)
    httproute.yaml        — Gateway API HTTPRoute → kong/kong parentRef; konghq.com/plugins
    servicemonitor.yaml   — ServiceMonitor in monitoring namespace (Prometheus/Mimir scraping)
    scaledobject.yaml     — KEDA ScaledObject; triggerType: prometheus | http | sqs
```

Key values structure:
- `keda.enabled: true` suppresses `replicas:` from Deployment (KEDA controls replica count)
- `httpRoute.enabled` gates both HTTPRoute and the `konghq.com/protocol` Service annotation
- `serviceMonitor.enabled` gates ServiceMonitor + adds a metrics port to Service and Deployment
- Three-layer override: chart defaults → `deployments/<team>/<app>/values.yaml` → `environments/<env>/values.yaml`

KEDA trigger types and their required values keys:
- `prometheus` → `keda.prometheus.{serverAddress, metricName, query, threshold}`
- `http` → `keda.http.{url, targetPendingRequests}`
- `sqs` → `keda.sqs.{queueURL, queueLength, awsRegion}` (uses pod identity — no static keys)

## Agentic capabilities
- Detect clusters missing `model` label (not properly registered)
- Generate PR to add a new team app config to teams/
- Generate PR to add a new customer to saas/customers/
- Detect ApplicationSet drift (sync warnings, failed syncs)
- Weekly scan: list clusters by model breakdown
- Flip k8s-manifests enforcementAction warn→deny for a policy after compliance confirmed
