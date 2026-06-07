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

## P2 Platform Core additions

### cert-manager (`applicationsets/workload/cert-manager.yaml`)
Deploys cert-manager v1.16.3 to every workload cluster. Issues the Kong wildcard TLS cert via DNS-01/Route53 (Let's Encrypt). Pod Identity grants cert-manager `route53:ChangeResourceRecordSets` — provisioned in aj-infra-platform. Images route through ECR `quay/` pull-through cache. ClusterIssuers (`letsencrypt-prod`, `letsencrypt-staging`) and the `kong-wildcard-tls` Certificate live in `charts/kong-gateway/`.

### Kong platform plugins (`charts/kong-gateway/plugins/`)
Three platform-level Kong plugins deployed alongside the Gateway:
- `correlation-id` → `KongClusterPlugin` (`global: "true"`) — adds X-Correlation-ID to every request
- `jwt` → `KongPlugin` in `kong` namespace — JWT validation; teams attach via annotation
- `rate-limiting` → `KongPlugin` in `kong` namespace — 1000 req/min per consumer, Valkey-backed; teams attach via annotation

Teams reference plugins:
```yaml
annotations:
  konghq.com/plugins: jwt,rate-limiting   # in their HTTPRoute
```

### Canary deployments (`charts/rollout-template/`)
Helm chart implementing Argo Rollouts canary pattern with Gateway API traffic splitting. Replaces the standard Deployment with an Argo `Rollout`. Argo Rollouts patches HTTPRoute `backendRefs` weights in real time.

```
templates/
  rollout.yaml            — Rollout (canary strategy, stableService + canaryService)
  services.yaml           — stable Service + canary Service (weights patched at runtime)
  httproute.yaml          — HTTPRoute: stable=100/canary=0 initially; Rollouts patches weights
  analysis-template.yaml  — Prometheus error-rate + p99 latency checks before auto-promote
```

Canary flow: image update → canary pods created → traffic split at `canary.weight` % → AnalysisTemplate runs 5 Prometheus checks over 5 min → pass: auto-promote to 100% stable; fail: auto-rollback. `canary.pauseDurationSeconds: 0` disables auto-promote (prod pattern — requires manual approval).

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

## File Naming Conventions

| Resource | Location | Naming |
|---|---|---|
| Team namespace | `teams/<team>/namespace.yaml` | fixed filename |
| Team app | `teams/<team>/<app>.yaml` | app slug matches Helm release name |
| SaaS customer | `saas/customers/<customer>.yaml` | customer slug, lowercase |
| Helm values | `charts/<component>/values/<env>.yaml` | env = dev/staging/prod or nonprod/prod |
| ApplicationSet | `applicationsets/workload/<component>.yaml` | component matches Application name prefix |

## Important Invariants

- All ApplicationSets track `main` branch — PRs required for any change
- Team namespace YAMLs drive the git-file-generator in `apps.yaml` AppSet
- Cluster Secrets must have `tier: workload` + `environment` + `model` + `auto_sync` labels
  for ApplicationSet generators to pick them up
- Sync-wave -1 on namespace ApplicationSets (namespace must exist before app workloads)
- `auto_sync: "true"` → dev + staging; `auto_sync: "false"` → prod (manual sync in ArgoCD UI)
