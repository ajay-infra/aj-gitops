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
│       │   gateway-api-crds.yaml, aj-cluster-baseline.yaml, keda.yaml — all fully wired, values exist
│       └── _disabled/  — arc-controller.yaml, gatekeeper.yaml, falcon.yaml, moved here 2026-08-24;
│                          inert (no directory.recurse), see Known Gaps below to re-enable
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

## Route53 ownership — five writers, one zone

Five different things write to the hosted zone. Knowing which owns what is the
difference between a safe cutover and a deleted production record.

| Writer | Owns | Lifetime |
|---|---|---|
| **Terraform** (`aj-tf-module-cloudfront`) | `blue.<domain>`, `green.<domain>`, the **`active.<domain>` cutover CNAME**, the apex A/alias, and ACM DNS-validation CNAMEs | Permanent |
| **cert-manager** | `_acme-challenge.*` **TXT**, for DNS-01 validation only | Seconds — created then deleted |
| **external-dns** | Records for Ingress / `type: LoadBalancer` Services, plus its own TXT registry entries | Follows the workload |
| **ACK Route53 controller** | ACM DNS-validation CNAMEs, for certificates the ACK ACM controller requests | Permanent |

> **Correction (2026-08-28).** An earlier version of this table credited the
> **ACK ACM controller** with writing its own validation records. It does not.
> The ACM controller requests the certificate and then waits for validation it
> cannot perform; AWS's documentation points at the separate **ACK Route53
> controller** for the CNAMEs. Deploying acm alone leaves every public
> certificate in `PENDING_VALIDATION` indefinitely — which is why the two are
> installed as a unit by a single `install_ack_certificates` toggle.

**cert-manager does NOT manage blue/green traffic records.** It only ever
creates the ephemeral ACME challenge TXT. Everything about which colour serves
traffic is Terraform's, and the cutover is one `active_color` value in
`edge.tfvars`.

### Why the ACK Route53 controller cannot clobber the others

The fifth writer is the one with the most obvious potential to repeat Session
7's external-dns mistake — a DNS writer holding deletion rights over records it
did not create. So its blast radius is bounded by **IAM**, not by chart
configuration that anyone can edit. `aj-infra-platform/ack.tf` scopes it three
ways simultaneously:

| Constraint | Condition key | Effect |
|---|---|---|
| CNAME records only | `ChangeResourceRecordSetsRecordTypes` | cert-manager's `_acme-challenge` **TXT** records are out of reach |
| Names beginning `_` | `ChangeResourceRecordSetsNormalizedRecordNames` | `blue.`, `green.`, `active.`, apex and every workload record are unmatched |
| `CREATE` + `UPSERT` | `ChangeResourceRecordSetsActions` | `DELETE` is not granted at all |

Plus a single hosted zone in `Resource`. It therefore cannot remove a record
even if the controller is compromised or misconfigured — the difference from
external-dns, whose `policy: sync` was one edited value away from deleting
production records.

### Why external-dns cannot clobber the others

Two properties, both load-bearing:

- **`txtOwnerId` is unique per cluster** — passed by the ApplicationSet as
  `{{name}}`, so blue and green never claim each other's records.
- **`policy: upsert-only` in prod and in the default** — external-dns creates
  and updates but never deletes. `sync` is set explicitly in dev and staging,
  where reclaiming records from deleted Ingresses matters more than the blast
  radius of a mistake.

The default was briefly `sync` (2026-08-27) because `_default.yaml` was derived
from `dev.yaml` on the assumption that dev is the most conservative profile. For
external-dns that is backwards: dev deletes, prod does not. Any cluster without
a profile — `prod-regulated`, `team-a-prod`, `internal-tools` — would have
inherited deletion rights over a shared zone containing Terraform's cutover
records. Corrected the same day.

## Values resolution — layered, with a default

Every workload ApplicationSet loads two value files:

```yaml
ignoreMissingValueFiles: true
valueFiles:
  - $values/charts/<name>/values/_default.yaml     # always
  - $values/charts/<name>/values/{{values.env}}.yaml  # overrides, if it exists
```

`{{values.env}}` is the cluster Secret's `environment` label — the environment
*directory name*, not a tier. Real labels today are `dev`, `staging`, `prod`,
`prod-regulated`, `internal-tools` and `team-a-prod`, and `provision-eks` lets
an operator name a cluster anything.

Before 2026-08-27 a label with no matching file meant a **missing `valueFiles`
source and a permanent sync error** — the failure that put three ApplicationSets
in `_disabled/`, and which `keda` was suffering silently in the *active*
directory while pointing at a `charts/keda/values/` that did not exist at all.

`_default.yaml` is derived from each chart's most conservative existing profile.
A cluster nobody wrote a profile for gets the smallest safe configuration rather
than a production one, and never a sync error.

**Adding a per-environment profile is optional.** Add one when a cluster needs
to differ; otherwise the default applies. Do **not** add a file per cluster out
of habit — that is what created the gap.

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
     → kubectl apply projects/<class>/platform.yaml
     → kubectl apply projects/<class>/workloads.yaml
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
confirmed by directory listing, not just a doc claim. Disabled 2026-08-24, not
deleted — moved to `applicationsets/workload/_disabled/`, which ArgoCD's
`bootstrap-workload-platform` Application never syncs (no `directory.recurse`, so
subdirectories are invisible to it):**

| ApplicationSet | References | Exists? |
|---|---|---|
| `_disabled/arc-controller.yaml` | `$values/charts/arc-controller/values/{{env}}.yaml` | ❌ no `charts/arc-controller/` dir at all |
| `_disabled/gatekeeper.yaml` | `$values/charts/gatekeeper/values/{{env}}.yaml` | ❌ no `charts/gatekeeper/` dir at all |
| `_disabled/falcon.yaml` | `$values/charts/falcon/values/{{env}}.yaml` | ❌ no `charts/falcon/` dir at all |

Before this fix, all three used the same live `tier: workload` cluster generator as
the working ApplicationSets (`arc-runners`, `cloudability`, `external-dns`, `kong`,
`keda`) — the moment a workload cluster registered with ArgoCD, all three would have
gone into a permanent sync error (missing Helm `valueFiles` source), not silently
skipped. Not caught earlier only because no workload cluster has been registered with
ArgoCD yet.

**To re-enable one:** add the real `charts/<name>/values/<env>.yaml` files (real Helm
values, not fabricated ones — needs actual Gatekeeper/Falcon/ARC-controller config
decisions this session didn't have context to make, e.g. a real CrowdStrike CID/secret
for Falcon, a real GitHub App's credentials for ARC), then `git mv` the file back up
to `applicationsets/workload/`. See `applicationsets/workload/_disabled/README.md`.

**`onboard-saas-customer` (in `aj-skill-farm`, marked "implemented" in the farm's
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

---

## `aj-cluster-baseline` ApplicationSet excludes the policy test fixtures

`directory.recurse: true` deploys every YAML file in the repo. `aj-cluster-baseline`
also contains `policies/tests/samples/` — real manifests that exist to be fed to
`gator verify`, not to be applied to a cluster. Several are deliberately
non-compliant (privileged Pods, `:latest` tags, missing resource limits), and
one is a live ACK ACM `Certificate` that would request an actual certificate
from AWS.

They are inside the pinned `v1.0.0` tag, so this was latent rather than
theoretical — it has not fired only because no cluster is provisioned yet.

```yaml
directory:
  recurse: true
  exclude: "policies/tests/**"
```

**The general shape is worth remembering:** `recurse: true` against a repo that
also holds test fixtures will deploy the fixtures. Any repo added to an
ApplicationSet this way needs checking for files that are valid Kubernetes
objects but are not meant to exist in a cluster.


---

## Class isolation — why this tree is duplicated

`applicationsets/workload/` and `projects/` exist twice, once per class. That is
deliberate and it is the whole point.

**What it replaces.** Every workload ApplicationSet used to select on
`tier: workload` and nothing else, while the cluster Secret written by
`bootstrap-workload.yml` carries `class`, `customer`, `kind` and `stage`. No
selector read any of them. A SaaS cluster would have inherited the entire
product platform stack the moment it registered, and every edit to any
ApplicationSet reached both models in the same sync.

**Two boundaries, not one.**

1. *Credentials.* Each hub is its own cluster and holds only its own class's
   cluster Secrets. A product hub has no credential for a SaaS cluster, so it
   cannot sync to one whatever a manifest says.
2. *Config.* Each hub's bootstrap points at `applicationsets/workload/<class>/`
   only. Editing the SaaS keda ApplicationSet cannot change the product one,
   because they are different files.

The first alone is not enough: separate hubs syncing one shared directory still
means one merge changes both models at once.

**One model runs at a time.** This is not two businesses operated in parallel
that must be kept in step — it is one business you have committed to, with the
other tree dormant. If both ever run they are separate offerings with separate
chargeback, and matching versions is not a goal.

So the duplication has no ongoing cost. There is no "both sides" to bump: you
change the tree you are running, and the other one sits still.

**What that does mean is that a dormant tree is a SNAPSHOT, not a maintained
thing.** Chart versions, `targetRevision` pins and `versions.yaml` entries for
the inactive class freeze at the day the split was made, and keep freezing.
Activating that class later is not `apply` — every pin in it is as old as the
last time anyone looked, including ones with CVEs published since.

Treat activation as a version review: read the pins, bump what needs bumping,
then apply. The tree tells you what the shape is, not what is current.

The same applies to the hubs. `envs/central/<class>/` in aj-infra holds tfvars
for four hubs; provisioning is a separate act. An unprovisioned hub costs
nothing, so a dormant class costs nothing — run the pipeline for the class you
are actually operating.

`class: <class>` is also on every selector. Redundant while each hub holds only
its own Secrets — kept because a mis-registration should fail to match rather
than spread.

**AppProject destinations are `server: "*"`, scoped by the hub.** They used to be
globs on cluster names (`https://ai-search-dev.*`). The Secret's `server` is the
EKS API endpoint (`https://A1B2C3.gr7.us-east-1.eks.amazonaws.com`), which no
such glob can match — every Application in the `workloads` project would have
been rejected at first sync with "destination is not permitted in project". The
hub split makes `*` the honest answer: there is no credential for the other
class to reach.
