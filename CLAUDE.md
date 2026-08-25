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

policies/
  constraints/                # Constraint objects (enforcement rules per namespace)
    allowed-registries.yaml
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
