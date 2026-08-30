# Changelog

All notable changes to this repo are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Changed — renamed from `k8s-manifests` to `aj-cluster-baseline`
Three reasons, in increasing order of consequence:

1. It was the only infra repo not named `aj-*` — 21 of 23 are, and the other exception is a product.
2. It did not distinguish this repo from `aj-platform-gitops`, which is *also* Kubernetes manifests synced by ArgoCD. The real split is control plane (**what goes where**) versus payload (**what runs inside a workload cluster**).
3. It said nothing about the property that actually governs the repo: **synced verbatim to every cluster from one pinned tag, no templating.** That is why there is no `env` namespace label, why `allowedLines` can only live in one place, and why `apps/` never belonged.

**The third reason was not cosmetic.** `apps/` is the one directory whose purpose is to *differ* per environment. Under a name meaning "cluster baseline" it would have looked obviously misplaced; under "k8s manifests" it looked at home, so nobody questioned it and `recurse: true` swept it up — applying three environments' patch fragments to every cluster (`aj-platform-gitops#14`).

The test for what belongs here is now written in `CLAUDE.md`: **would it be correct, unchanged, on every workload cluster in the estate?**

### Changed — one rule for who declares a namespace
**Every namespace is declared exactly once, with the full label set, by the repo that owns the component — and nothing creates one implicitly.** `falcon-system` moves to `aj-infra-platform/namespaces.tf` (Terraform installs Falcon), taking its Pod Security and Gatekeeper-exemption labels with it. `cloudability` stays here: ArgoCD installs it, but its manifests live in this repo.

It was declared here **and** created by `create_namespace = true`, so whichever landed first decided whether it had labels.

### Added — a gator case pinning the label set the two repos must agree on
`ns-platform-terraform.yaml` is a platform namespace exactly as `namespaces.tf` renders it, asserted admissible. Eleven platform namespaces were Helm-created and unlabelled until 2026-08-29, so `require-cost-labels` and `require-segment-label` would have rejected nine of them — the platform could not have installed itself onto a cluster running these policies. If the two label sets ever diverge, this case fails before a cluster does.

### Removed — the last of Kong
`cert-manager/certificate-kong-wildcard.yaml` issued a wildcard into the `kong` namespace for a Gateway that no longer exists, and `apps/frontend/base/httproute.yaml` still had `parentRefs` pointing at it. Both now target `apisix`, the estate's only `edge` namespace.

### Added — `require-product-line`, shipped in dryrun
- **SaaS namespaces must declare which product line they belong to** (`platform.aj/product-line`). SaaS has two independent chargeback axes where product has one: revenue is contracted per **customer** and recognised per **product line**, and a customer buys several lines while a line is sold to many customers. `require-cost-labels` carries the first; this carries the second. Neither derives from the other — collapsing them is the mistake `Model` made.
- **Vocabulary is a constraint parameter** (`allowedLines`: `crm`, `analytics`, `merch`, `pos`, `ticketing`, `shared`), not template Rego and **not the org SCP**. The SCP checks the tag is *present*; only this checks it is *real*. A closed list in an SCP would mean editing the one control an account administrator cannot override every time the business names a product. Adding a line is a one-line edit here.
- **`shared` is reserved**, on the same reasoning as `pooled` for `platform.aj/customer`. Auth, notifications and the event bus serve every line; without a word for that, absent-because-cross-cutting is indistinguishable from absent-because-forgotten. `shared` spend is allocated by a rule — the label's job is to say a rule is needed.
- **Ships as `dryrun` for a different reason to `require-product-code`.** That one matches namespaces whose values are wrong. This one matches **no namespace at all** — nothing in the estate is labelled `platform.aj/class: saas` yet. A constraint that selects nothing is indistinguishable from one that finds nothing wrong, so dryrun puts it in the audit log instead of a clean pass. Flip to `deny` when `onboard-saas-customer` emits the label.
- **SaaS only.** On a product namespace the value would be `shared` or empty on every one, and a field with one possible value is decoration.
- Seven `gator` cases, including two that assert the constraint is *scoped* rather than merely quiet, and an empty-string case the missing-label rule structurally cannot catch.
- Full profile: `aj-infra-context/arch/tag-profiles.md` §5.

### Added — `require-product-code`, shipped in dryrun
- `team` carries the **product code** (`pim`/`prd` + number), not a descriptive slug — it is the key chargeback groups by.
- **Ships as `enforcementAction: dryrun`, deliberately.** The estate's namespaces carry `team: product` and `team: platform`; enforcing today would reject **every one of them**. Dryrun reports to the audit log without blocking, which is the honest state while codes are assigned. Flip to `deny` once they are.
- **Split from `require-cost-labels` rather than folded in**, because that constraint *is* enforcing and must stay that way. One constraint at `deny`, one at `dryrun`, each honest about its readiness.
- **Only applies to `class: product`.** Platform namespaces are overhead, not a product — forcing a code onto `monitoring` would invent one purely to satisfy a rule, which is how a taxonomy starts lying. `class: saas` was in this list and was removed in #15: SaaS is a separate tagging profile whose chargeback keys are `customer` and `product-line`.
- The pattern is a **constraint parameter**, not template Rego: a wrong pattern in an enforcing constraint rejects every namespace it matches, so it needs to be a one-line fix with no policy change.



### Added — FinOps cost attribution labels
- **`require-cost-labels` constraint** — every namespace must carry `team`, `platform.aj/class` and `platform.aj/customer`. AWS tags attach to nodes and many pods share a node, so a tag cannot attribute container cost; Cloudability allocates from namespace labels. Without these, spend is attributable no further than "this cluster" — exactly wrong for a pooled SaaS cluster where one node runs several customers.
- Labels applied to all five namespaces. `falcon-system` had no `team` label at all.
- **`team` and `class` are allowed to differ** — `data-access` is operated by platform and paid for by product.
- **An empty `platform.aj/customer` is rejected explicitly.** The reserved values `pooled` and `internal` exist so absent means *forgotten*; an empty string would reintroduce the ambiguity they were chosen to remove.
- Four `gator` cases including a dedicated-customer namespace and the empty-customer rejection.

### Fixed — the taxonomy required an `env` label that cannot exist
`label-taxonomy.md` listed `env` as a required namespace label. **No namespace had one, and none could:** `aj-cluster-baseline` is synced verbatim to every cluster from a single pinned tag with no templating, so a static `env` label would be wrong in every cluster but one. Environment is a cluster property. Corrected in the taxonomy and documented here.



### Fixed — the segment label was decorative, and the policies were fail-open
- **Network policies now select on the namespace label** (`io.cilium.k8s.namespace.labels.platform.aj/segment`) instead of hardcoded namespace names. The previous version contained **zero references** to the label it was supposedly built around — it matched `io.kubernetes.pod.namespace` against fixed lists.
  - **This was fail-open.** Cilium leaves an endpoint unrestricted until some policy selects it, so a namespace absent from those lists received **no policy at all** and had full connectivity, silently. Onboarding a team would have produced an unsegmented namespace with nothing to indicate it — the exact inverse of the intended property.
  - Now self-extending: label a namespace and it is segmented, with no file to edit.
  - ⚠ The selector form `io.cilium.k8s.namespace.labels.platform.aj/segment` is valid (one slash, per Kubernetes label rules) but has not been exercised against a live cluster. Verify with `cilium policy get` on first deploy.
- **`require-segment-label` Gatekeeper constraint** — a namespace cannot be created without a valid `platform.aj/segment`. Turns fail-open into fail-to-create. Two distinct violations, because "you forgot a label" and "that is not a segment" need different fixes and a single generic message sends people looking in the wrong place. Three `gator` cases, all passing. System namespaces excluded: the cluster creates them before any policy exists.

### Changed — `platform.aj/tier` renamed to `platform.aj/segment`
`tier` already meant five different things here: cluster shape (now `kind`/`stage`/`size`), the central `nonprod|prod` split, the ArgoCD `workload|central` Secret label, RBAC tiers in `register-namespace`, and customer **pricing** tiers in `onboard-saas-customer`. A sixth meaning, added one session after recording that this exact trap exists, was not worth the familiarity.



### Added — network tiering (`platform.aj/segment`)
Implements `aj-infra-context/arch/network-segmentation.md`. **Allow rules only; enforcement is not switched on.**

- **`network-policies/`** — `CiliumNetworkPolicy` per tier. Cilium is installed and, before this, **not one policy existed** — every pod could reach every other pod. Rules key on `io.kubernetes.pod.namespace`, which Cilium adds to every endpoint automatically, so they work without every workload author remembering a label and cannot be bypassed by omitting one.
  - `platform` is deliberately **not reachable from `app`** — a compromised workload must not have a network path to OPA, External Secrets or cert-manager, which hold the credentials and make the decisions that constrain it. The single exception is OPA from `edge`, which is the authorization call path.
  - OPA has **no `world` egress**: it must not fetch JWKS over the internet per request. Keys live in policy data.
- **Karpenter tier pools** — new `edge`, `platform` and `data` NodePools; `platform.aj/segment: app` added to `frontend`, `backend` and `gpu`. Tier and `workload` are separate axes and compose; neither replaces the other.
- **`karpenter/node-classes/data-access.yaml`** — the reason `data` is a tier rather than a label. **Aurora authorizes by security group and a security group cannot see pods**, only the node's ENI. So database reachability is only enforceable by controlling which nodes carry a trusted group, which makes it a reviewable scheduling decision instead of an ambient property.
- Namespace `platform.aj/segment` labels on `frontend`, `backend`, `data-access`.

### ⚠ Known-incomplete, deliberately
- **`karpenter.sh/data-access` security group does not exist.** It needs creating Terraform-side with Aurora's and Valkey's ingress narrowed to reference only it — blocked on `aj-infra-context#24` / `#15`. Until then the `data` pool will not provision, which is the correct failure mode: better a pod that will not schedule than one reaching the database because it landed on a broadly-permitted node.
- **`data.yaml` egress uses a placeholder `10.0.0.0/8`.** The data VPC does not exist. The /8 is deliberately obvious so it cannot be mistaken for a considered value.
- **Enforcement order is not optional:** label → allow → observe (Hubble) → `policyEnforcementMode`. Default-deny with incomplete allow rules is an outage whose cause is invisible without Hubble already running.

### ⚠ Contradiction surfaced, not resolved
`namespaces/workload-namespaces.yaml` calls `data-access` "DB proxy, cache adapter services", while `karpenter/node-pools/backend.yaml` justifies on-demand capacity by backend's "stateful connections to Aurora/Valkey". **Both cannot be true.** If backend connects directly, `data` is not a tier and the security-group boundary buys nothing. Recorded in both files rather than silently picking one.

### Changed — BREAKING
- **`kong/` removed; replaced by `apisix/` + `opa/`.** Follows `aj-infra-platform#10`, which swapped Kong for APISIX + standalone OPA. Rationale: `aj-infra-context/arch/gateway-selection.md`.
  - `kong/jwt.yaml` has **no direct replacement, deliberately.** There is no JWT plugin at the gateway any more. Verification moved into OPA (`opa/policy-authz.yaml`), which makes trusted issuers *data* rather than gateway configuration.
  - `kong/correlation-id.yaml` → the `request-id` plugin in `apisix/plugin-config-authz.yaml`.
  - `kong/rate-limiting.yaml` → `limit-count` in `apisix/plugin-config-ratelimit.yaml`, keyed on consumer with fallback to remote address.

### Added
- **`opa/policy-authz.yaml`** — `package apisix.authz`. Verifies the bearer token with `io.jwt.decode_verify` against issuers held in policy data, then authorizes on the resulting claims. Returns `{allow, reason, status_code}` in the shape the APISIX `opa` plugin expects. Distinguishes 401 (cannot establish who the caller is) from 403 (known and not permitted), because collapsing both makes debugging painful.
- **`opa/policy-issuers.yaml`** — trusted issuers as data, expressed as a Rego package rather than a JSON data ConfigMap so the document path is deterministic (`data.issuers`) instead of derived from namespace and name. Ships with `providers := []`, so the gateway denies everything until a Keycloak realm exists. **That is the correct failure mode**, and there is a test for it.
- **`opa/tests/authz_test.rego`** — 9 behaviour cases run by a new `apisix-authz-tests` CI job. Signs **RS256** tokens against a JWKS, because production uses `cert` with a JWKS and `io.jwt.decode_verify` takes `secret` for HMAC — an HMAC test would pass while proving nothing about the path that actually runs. Covers: public paths need no token; missing, garbage, wrong-issuer and wrong-audience tokens denied; valid token allowed; missing tenant → 403; missing roles denied; and **an empty issuer list denies rather than default-allows.**
  - The RSA key in that file is a throwaway fixture, labelled as such, used nowhere else.

### Note — rate limiting is per-pod until Valkey exists
`limit-count` is set to `policy: local`, so counters are per-gateway-pod and the effective limit is rate × replicas. Shared counters need a real Valkey endpoint, and `aj-tf-module-valkey` has no consumer (`aj-infra-context#15`) with the engine choice deferred (`#17`). Flagged in the file. **Do not ship `local` to production and describe it as a global limit.**

### Added
- **`deny-acm-exportable`** — a ConstraintTemplate + Constraint rejecting any ACK ACM `Certificate` (`acm.services.k8s.aws`) that sets `spec.exportTo`.
  - `exportTo` requests an **exportable** public certificate: **$7 per FQDN and $79 per wildcard, charged at issuance AND at every renewal** on a 198-day validity — roughly **$158/year** per wildcard. Standard ACM certificates are free, and the one case `exportTo` serves (in-cluster TLS termination) is already covered free by cert-manager.
  - **This is admission control because nothing else can do the job.** ACM has no IAM condition key for the export option, and the charge lands at *issuance* rather than at export — so withholding `acm:ExportCertificate` stops the private key leaving but does not stop the bill. Rejecting the object before admission is the only control that prevents the spend, because the controller then never calls `RequestCertificate` with export enabled.
  - **Cluster-wide and unconditional**, unlike the workload constraints which are scoped to prod namespaces. An exportable certificate costs the same in dev, and dev is where someone experimenting would reach for `exportTo` first.
  - Three `gator` cases, in both directions: a certificate without `exportTo` must produce no violations (a constraint that denied everything would silently stop the estate issuing any certificate), and both a plain and a wildcard `exportTo` must be denied — the wildcard case asserting on the cost figure so the message keeps carrying the reason.

### Fixed
- `.github/workflows/ci.yml`'s `yaml-lint` and `validate-k8s` jobs both referenced a `cloudability/` directory that has never existed in this repo — reproduced locally: `yamllint` fails immediately with `[Errno 2] No such file or directory: 'cloudability/'`, exit code 255. This broke CI on every single PR to this repo, unconditionally, regardless of what the PR actually changed. Removed the `cloudability/` reference from both commands until that TODO (see below) is actually done.
- `CLAUDE.md`'s "Known TODOs" listed "Add `.sops.yaml` and SOPS-encrypted ExternalSecret values" as fully open — `.sops.yaml` already exists. The framing was also confused: ExternalSecrets don't hold secret material client-side (they hold a `remoteRef.key` pointing at a Secrets Manager ARN), so there's nothing in them for SOPS to encrypt. Corrected the TODO to describe what's actually still open: real KMS key ARNs in `.sops.yaml` (currently `REPLACE_WITH_*` placeholders) and real Secrets Manager ARNs in `external-secrets/*.yaml` (same placeholder pattern).
- No `skills.md` existed at all — added one, describing the repo layout, CI checks, and cross-repo dependencies (`aj-tf-module-scps` for KMS ARNs, `aj-tf-module-aurora`/`aj-tf-module-valkey` for Secrets Manager ARNs, `aj-tf-module-ecr` for pull-through cache prefixes). Without it, the `add-opa-policy` skill and any freeform `infra-developer` change here had no repo-context source per the farm's two-source context model.

## [Unreleased, pre-existing]
No prior releases — this repo isn't consumed as a versioned Terraform module by anything (pure GitOps manifests, synced directly from `main`), so there's no tagging convention to follow here unlike the `aj-tf-module-*` repos.
