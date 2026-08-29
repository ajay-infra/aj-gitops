# CLAUDE.md — k8s-manifests

> GitOps manifest repository. Synced to all registered workload clusters by ArgoCD.

---

## What This Repo Does

Kubernetes manifests deployed to every EKS workload cluster via ArgoCD ApplicationSets.
Terraform never touches these resources — everything here is GitOps-managed.

Covers:
- OPA Gatekeeper ConstraintTemplates + Constraints (policy enforcement)
- OPA Gatekeeper mutation policies (ECR pull-through cache image rewrite)
- Karpenter NodePool + EC2NodeClass (node autoscaling config)
- KEDA ScaledObjects (event-driven pod autoscaling)
- Kong KongPlugin CRDs (JWT, rate-limiting, correlation-id)
- ExternalSecrets (pull Aurora + Valkey credentials from Secrets Manager)
- Namespace definitions (platform + workload namespaces)
- Falcon DaemonSet (CrowdStrike runtime security sensor)

---

## Where It Fits

**Architecture layers:** L8 (Secrets), L9 (API Gateway), L10 (App Workloads), L11 (Policy)
**Synced by:** ArgoCD on each central cluster hub, via `applicationsets/workload/k8s-manifests.yaml` in `aj-platform-gitops`
**Sync policy:** Auto-sync on dev + staging clusters; manual gate on prod clusters
**Cluster selector:** All clusters with label `tier: workload` registered with the ArgoCD hub

---

## How to Use

You do not apply this repo manually. ArgoCD handles it automatically after the workload cluster is registered:

```
provision-eks.yml apply → argocd-register stage creates cluster Secret
→ ArgoCD detects new cluster matching tier=workload label
→ workload-k8s-manifests ApplicationSet generates Application for new cluster
→ ArgoCD syncs entire repo to the cluster
```

To add or change a manifest:
1. Edit or add YAML files in the appropriate subdirectory
2. Open a PR — CI validates (yamllint + kubeconform)
3. Merge → ArgoCD auto-syncs to dev + staging within ~30 seconds
4. Prod requires manual sync approval in the ArgoCD UI

---

## Repo Layout

```
external-secrets/
  aurora-connection.yaml      # ExternalSecret: Aurora endpoint + IAM auth config
  cluster-secret-store.yaml   # ClusterSecretStore: ESO → Secrets Manager backend
  valkey-auth.yaml            # ExternalSecret: Valkey auth token + endpoint

falcon/
  daemonset.yaml              # Falcon sensor DaemonSet on every node (falcon-system ns)

karpenter/
  node-classes/
    general-purpose.yaml      # EC2NodeClass: instance types, AMI, user-data
  node-pools/
    backend.yaml              # NodePool: backend workload nodes
    frontend.yaml             # NodePool: frontend/edge nodes
    gpu.yaml                  # NodePool: GPU nodes for LLM inference

keda/
  backend-scaler.yaml         # ScaledObject: backend Deployment — Prometheus scaler
  frontend-scaler.yaml        # ScaledObject: frontend Deployment — HTTP request rate

kong/
  correlation-id.yaml         # KongPlugin: inject X-Correlation-ID on all requests
  jwt.yaml                    # KongPlugin: JWT validation for authenticated routes
  rate-limiting.yaml          # KongPlugin: per-consumer rate limiting (backed by Valkey)

namespaces/
  platform-namespaces.yaml    # argocd, monitoring, falcon-system, cloudability, arc-runners
  workload-namespaces.yaml    # frontend, backend, llm, search, data-access

network-policies/             # CiliumNetworkPolicy per tier — ALLOW rules only
  README.md                   #   read before adding default-deny
  edge.yaml app.yaml          #   platform.aj/tier boundaries
  data.yaml platform.yaml

apisix/                       # ApisixPluginConfig — gateway plugin bundles
  plugin-config-authz.yaml    #   request-id + opa. NO jwt plugin — see opa/
  plugin-config-ratelimit.yaml#   limit-count; policy: local until Valkey exists

opa/                          # authorization policy for APISIX (NOT Gatekeeper)
  policy-authz.yaml           #   package apisix.authz — verifies JWT + authorizes
  policy-issuers.yaml         #   package issuers — trusted issuers AS DATA
  tests/authz_test.rego       #   opa test; RS256/JWKS, 9 cases

policies/
  constraints/                # Constraint objects (enforcement rules per namespace)
    allowed-registries.yaml
    deny-acm-exportable.yaml  # cluster-wide, not namespace-scoped — see below
    deny-latest-tag.yaml
    no-privileged-containers.yaml
    require-pod-disruption-budget.yaml
    require-probes.yaml
    require-resource-limits.yaml
  mutations/                  # AssignImage: ECR pull-through cache image rewrite
    rewrite-docker-io.yaml
    rewrite-ecr-public.yaml
    rewrite-ghcr-io.yaml
    rewrite-k8s-registry.yaml
    rewrite-quay-io.yaml
  templates/                  # ConstraintTemplate CRDs (Rego policy schema)
    allowed-registries.yaml
    deny-acm-exportable.yaml
    deny-latest-tag.yaml
    no-privileged-containers.yaml
    require-pod-disruption-budget.yaml
    require-probes.yaml
    require-resource-limits.yaml
```

---

## OPA Gatekeeper Policy Enforcement

Policies use `enforcementAction: warn` in dev/staging and `deny` in prod. This is encoded in the Constraint YAML files themselves — no per-env paths needed.

Mutation policies (image rewrites) apply on ALL environments. Developers write `nginx:1.27`; the cluster transparently pulls `<account>.dkr.ecr.<region>.amazonaws.com/dockerhub/library/nginx:1.27`.

---

## Known TODOs

- [x] `.sops.yaml` exists — but ["SOPS-encrypted ExternalSecret values" was never a coherent
      task: ExternalSecrets don't hold secret material client-side, they hold a
      `remoteRef.key` pointing at a Secrets Manager ARN, so there's nothing in them for
      SOPS to encrypt. What's actually still open: `.sops.yaml`'s `kms:` entries are all
      `REPLACE_WITH_*_SOPS_KEY_ID` placeholders (real ARNs come from `aj-tf-module-scps`
      outputs), and every `external-secrets/*.yaml`'s `remoteRef.key` is still
      `REPLACE_WITH_*_SECRET_ARN` (real ARNs come from `aj-tf-module-aurora`/`aj-tf-module-valkey`
      outputs). Also note `.sops.yaml`'s `path_regex` patterns target `envs/dev|staging|prod/*.yaml`,
      but no `envs/` directory exists in this repo yet either.
- [ ] Fill in real KMS key ARNs in `.sops.yaml` (from `aj-tf-module-scps`) and real Secrets
      Manager ARNs in `external-secrets/*.yaml` (from `aj-tf-module-aurora`/`aj-tf-module-valkey`)
- [ ] Configure ArgoCD Image Updater: watch ECR for new image digests, open PRs automatically
- [ ] Add Cloudability agent manifest (or confirm it is fully handled by the ApplicationSet Helm install) — `ci.yml` referenced a `cloudability/` directory that never existed, breaking `yamllint`/`kubeconform` on every PR; removed the reference until this TODO is actually done
- [ ] Narrow Falcon OPA exclusion to `falcon-system` namespace only (already designed, needs Constraint update)
- [ ] Add PodDisruptionBudget manifests for all platform workloads

---

## `deny-acm-exportable` — the one constraint that exists to prevent a bill

Every other constraint here protects the cluster. This one protects the invoice,
and it is the only policy in the repo that is **cluster-wide and unconditional**
rather than scoped to prod namespaces.

`spec.exportTo` on an ACK ACM `Certificate` requests an **exportable** public
certificate: **$7 per FQDN and $79 per wildcard, charged at issuance AND at
every renewal** on a 198-day validity — about **$158/year** for one wildcard.
Standard ACM certificates are free.

**It is admission control because nothing else can do the job.** ACM has no IAM
condition key for the export option, and the charge lands at *issuance*, not at
export — so withholding `acm:ExportCertificate` stops the private key reaching a
Secret but does not stop the spend. Rejecting the object at admission is the only
control that prevents it, because the controller then never calls
`RequestCertificate` with export enabled.

It is not namespace-scoped because an exportable certificate costs the same in
dev, and dev is where someone experimenting would reach for `exportTo` first.

The one case `exportTo` serves — in-cluster TLS termination — is already covered,
free, by cert-manager. See `aj-infra-platform/ack.tf`.

---

## `opa/` is not `policies/` — two OPAs, two jobs

Easy to conflate, and conflating them wastes an afternoon.

| | `policies/` | `opa/` |
|---|---|---|
| Engine | Gatekeeper (OPA embedded in an admission controller) | standalone OPA (`opa-kube-mgmt`) |
| Decides | may this Kubernetes object be admitted | may this API request proceed |
| Called by | the API server, via admission webhooks | APISIX, via the `opa` plugin over HTTP |
| Tested with | `gator verify` | `opa test` |

Gatekeeper does **not** expose the Data API (`/v1/data/...`) that the APISIX
plugin queries, so one cannot be pointed at the other. Same language, different
deployment, different job.

## Why the JWT is verified in OPA rather than at the gateway

This is the load-bearing decision of the whole API layer, and it looks like an
implementation detail until you know the history.

A prior estate ran per-tenant JWT issuers as **gateway configuration** and
OOM-killed at ~24 of them against a 16-provider ceiling. Verifying in OPA makes
issuers **data** (`opa/policy-issuers.yaml`): adding a tenant is a ConfigMap
edit, an ArgoCD sync and a policy reload — no proxy rollout, no ceiling.

**The rule that follows, and it is absolute:**

> A tenant never appears in gateway configuration. Tenants are claims in the
> token and rows in policy data.

If `opa/policy-issuers.yaml` starts growing one entry per tenant, the identity
topology has regressed. Under Keycloak Organizations there should be **one**
issuer — tenants are organizations inside a single realm, distinguished by a
claim. More than one entry is legitimate only for a customer whose own IdP
genuinely cannot be brokered.

**Corollary worth keeping:** API keys and JWTs are different *authentication*
mechanisms that both land as input to the *same* policy. One authorization
surface, not two. That is why `with_consumer: true` is set on the `opa` plugin.

## An empty issuer list must deny

`policy-issuers.yaml` ships with `providers := []` because no Keycloak realm
exists yet, and the gateway therefore denies everything. That is the correct
failure mode and there is a test for it — an empty trust store must never mean
"trust anyone". If that test is ever deleted, assume the worst.

---

## Network tiering — `platform.aj/tier`

Design: `aj-infra-context/arch/network-tiering.md`. What matters when editing:

| tier | namespaces | reachable from |
|---|---|---|
| `edge` | `apisix` | the internet-facing NLB **only** |
| `platform` | `opa`, `cert-manager`, `external-secrets`, `monitoring`, … | cluster-internal; OPA from `edge` |
| `app` | `frontend`, `backend`, `llm`, `search` | `edge` only |
| `data` | `data-access` | `app` only |

### Three mechanisms, not one

Conflating these is where the difficulty comes from:

- **Where a pod runs** — Karpenter NodePools with `platform.aj/tier` labels and taints
- **What a pod can reach** — `network-policies/`
- **What a node can reach** — subnet, security group, route table (Terraform)

**Pods never run in public subnets.** All nodes are private; public subnets hold
the NLB, data subnets hold Aurora and Valkey. Scheduling isolates compute, not
traffic.

### Why `data` is a tier and not just a label

**Aurora authorizes by security group, and a security group cannot see pods** —
it sees the node's ENI. So "which pods may open a database connection" is only
enforceable by controlling which *nodes* carry a trusted security group. A pod
reaches the database because it was scheduled onto a `data` node, which makes
database access a reviewable scheduling decision rather than something every pod
in the cluster has by default.

`network-policies/data.yaml` expresses the intent; the security group enforces it.

### ⚠ Enforcement is NOT on, and the order matters

Cilium has no `policyEnforcementMode` set, so an endpoint is unrestricted until a
policy selects it. The moment a policy here selects a pod, that pod becomes
deny-by-default for the direction covered.

```
label → allow → observe (Hubble) → deny
```

Reversed, the cluster stops serving and the cause is invisible.

### ⚠ Unresolved contradiction

Two files disagree about who reaches the database:

- `namespaces/workload-namespaces.yaml` — `data-access` is "DB proxy, cache adapter services"
- `karpenter/node-pools/backend.yaml` — backend is on-demand because of "stateful connections to Aurora/Valkey"

If backend connects directly, `data` is not a tier and the security-group
boundary buys nothing. If data-access proxies, the boundary is real. The proxy
model is stronger and is what `data.yaml` assumes — but it costs a hop and a
proxy to operate, and should be decided rather than inherited.
