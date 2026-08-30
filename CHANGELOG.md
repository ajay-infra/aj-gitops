# Changelog

All notable changes to this repo are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased] (2)

### Fixed
- **The `aj-cluster-baseline` ApplicationSet deployed the policy test fixtures.** `directory.recurse: true` with no `exclude` deploys every YAML file in the repo, and `aj-cluster-baseline/policies/tests/samples/` holds real manifests that exist to be fed to `gator verify` — several deliberately non-compliant (privileged Pods, `:latest` tags, missing resource limits), plus a live ACK ACM `Certificate` that would request an actual certificate from AWS. They sit inside the pinned `v1.0.0` tag, so this was latent rather than theoretical; it has not fired only because no cluster is provisioned yet. Added `exclude: "policies/tests/**"`.
  - Found while adding the `deny-acm-exportable` constraint, whose own test samples would have been deployed the same way.
  - Worth generalising: `recurse: true` against a repo that also holds test fixtures deploys the fixtures. Any repo wired into an ApplicationSet this way needs checking for files that are valid Kubernetes objects but are not meant to exist in a cluster.

### Changed
- **Route53 ownership is now five writers, not four.** The ACK Route53 controller joins as the owner of ACM DNS-validation CNAMEs.
  - **Corrects an error in the previous table**, which credited the *ACK ACM controller* with writing its own validation records. It does not — it requests the certificate and then waits for validation it cannot perform. AWS's documentation points at the separate Route53 controller for the CNAMEs, which is why the two are installed as a unit.
  - Documented why the fifth writer cannot repeat Session 7's external-dns incident: its IAM is scoped to CNAME records only, names beginning `_`, and `CREATE`/`UPSERT` with no `DELETE`, plus a single hosted zone. Bounded by IAM rather than by chart configuration that anyone can edit.

### Fixed
- **Disabled the 3 broken ApplicationSets** documented in the previous entry (`arc-controller`, `gatekeeper`, `falcon`) rather than leaving them live and broken. Moved to a new `applicationsets/workload/_disabled/` subdirectory, which `bootstrap/*.yaml`'s `bootstrap-workload-platform` Application never syncs (confirmed: no `directory.recurse` set on that Application's source, so ArgoCD doesn't descend into subdirectories of `applicationsets/workload/`). Each file got a banner explaining why and how to re-enable; added `_disabled/README.md` with the same. Not deleted — the design work stays, just inert until real Helm values exist for each.

## [Unreleased]

### Changed — `k8s-manifests` is now `aj-cluster-baseline`
Repo renamed on GitHub; `repoURL`s, the ApplicationSet filename and its resource names follow. The old name broke the `aj-*` convention, did not distinguish that repo from this one (both are Kubernetes manifests synced by ArgoCD), and said nothing about its governing property — synced verbatim to every cluster from one pinned tag.

### Documented — `validatingWebhookIgnoredNamespaces` is the real exemption surface
A namespace listed there bypasses the Gatekeeper webhook **entirely** — not just the label constraints but `no-privileged-containers`, `allowed-registries`, `deny-latest-tag`, `require-probes` and `require-resource-limits`. Eleven namespaces are on it, identically in every environment including `prod-regulated`.

**This is invisible from the constraint files.** Their `excludedNamespaces` lists name five system namespaces; reading them alone tells you these eleven are covered. They are not. Kubernetes also matches a webhook's `namespaceSelector` against a Namespace object's *own* labels, so a namespace named here cannot be rejected at creation either — which corrects a claim made in `aj-infra-platform#14`: **five** of the unlabelled platform namespaces would have been rejected at admission, not nine. The other four were already exempt.

Now carries a header saying so. `apisix` and `opa` are deliberately absent — the gateway and the policy engine are evaluated like any workload.

### Removed — the rest of Kong
`charts/kong/` and `charts/kong-gateway/` were orphaned when the two ApplicationSets were deleted, `kong` was still in every Gatekeeper webhook exemption list, and `gateway-api-crds.yaml` still ordered itself "before workload-kong".

### Fixed
- No `skills.md` existed — added one, describing the ApplicationSet pattern, the `provision-eks.yml`/`argocd-register` dependency, and both gaps below so `infra-developer` and any future skill work here starts with accurate context.

### Documented (not fixed — real infrastructure work needed, not something to fabricate)
- `CLAUDE.md`'s "Repo Layout" tree was missing `charts/arc-runners/`, `charts/cloudability/`, `charts/external-dns/`, `charts/kong/`, `charts/kong-gateway/` — all five exist and are fully wired (confirmed via `find`). Added them.
- **Three workload ApplicationSets reference Helm values that don't exist**: `arc-controller.yaml`, `gatekeeper.yaml`, and `falcon.yaml` all reference `$values/charts/<name>/values/{{env}}.yaml` paths where `charts/<name>/` doesn't exist at all — confirmed by directly checking the filesystem, not just a doc claim. All three use the live `tier: workload` cluster generator (same as the working ApplicationSets), so this isn't a disabled/dormant config — it would fail to sync the first time a workload cluster is actually registered. Documented in `CLAUDE.md`'s new "Known Gaps" section rather than fixed, since writing real Gatekeeper/Falcon/ARC-controller Helm values requires actual configuration decisions this session doesn't have the context to make safely.
- **`onboard-saas-customer` (in `aj-agent-farm`, marked "implemented" in the farm's skills catalog) has no matching infrastructure in this repo.** Its `skill.md` describes a `saas-customer-namespaces` ApplicationSet watching `saas/customers/*.yaml` — grepped this entire repo for "saas": zero matches anywhere. If run today, the skill would successfully generate and merge a file that ArgoCD never picks up, with no error surfaced anywhere in that flow. Documented in `CLAUDE.md`'s Known Gaps.
