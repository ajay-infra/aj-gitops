# Changelog

All notable changes to this repo are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Fixed
- No `skills.md` existed — added one, describing the ApplicationSet pattern, the `provision-eks.yml`/`argocd-register` dependency, and both gaps below so `infra-developer` and any future skill work here starts with accurate context.

### Documented (not fixed — real infrastructure work needed, not something to fabricate)
- `CLAUDE.md`'s "Repo Layout" tree was missing `charts/arc-runners/`, `charts/cloudability/`, `charts/external-dns/`, `charts/kong/`, `charts/kong-gateway/` — all five exist and are fully wired (confirmed via `find`). Added them.
- **Three workload ApplicationSets reference Helm values that don't exist**: `arc-controller.yaml`, `gatekeeper.yaml`, and `falcon.yaml` all reference `$values/charts/<name>/values/{{env}}.yaml` paths where `charts/<name>/` doesn't exist at all — confirmed by directly checking the filesystem, not just a doc claim. All three use the live `tier: workload` cluster generator (same as the working ApplicationSets), so this isn't a disabled/dormant config — it would fail to sync the first time a workload cluster is actually registered. Documented in `CLAUDE.md`'s new "Known Gaps" section rather than fixed, since writing real Gatekeeper/Falcon/ARC-controller Helm values requires actual configuration decisions this session doesn't have the context to make safely.
- **`onboard-saas-customer` (in `aj-agent-farm`, marked "implemented" in the farm's skills catalog) has no matching infrastructure in this repo.** Its `skill.md` describes a `saas-customer-namespaces` ApplicationSet watching `saas/customers/*.yaml` — grepped this entire repo for "saas": zero matches anywhere. If run today, the skill would successfully generate and merge a file that ArgoCD never picks up, with no error surfaced anywhere in that flow. Documented in `CLAUDE.md`'s Known Gaps.
