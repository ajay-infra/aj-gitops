# Changelog

All notable changes to this repo are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added — the repo
One YAML per namespace, rendered by one chart into `Namespace` + `ResourceQuota` + `LimitRange`.

Replaces three half-built namespace lifecycles, none of which could run:

| Mechanism | Wrote / read | Existed? |
|---|---|---|
| `register-namespace` skill | `aj-platform-gitops/teams/<team>/namespace.yaml` | no `teams/` directory |
| `register-namespace.yml` pipeline | an Application pointing at `charts/namespace-template` | no such chart |
| `onboard-saas-customer` skill | `aj-platform-gitops/saas/customers/<customer>.yaml` | no `saas/` directory, nothing read it |

The pipeline also passed `model` and `env` as Helm parameters — `model` was deleted from the taxonomy for collapsing two orthogonal facts into one field, and `env` is pre-migration vocabulary.

### Added — `llm` and `search`, which no repo declared
`apps.yaml` in `aj-platform-gitops` deploys `llm-router` and `searxng` into them, and only `frontend`, `backend` and `data-access` were declared anywhere. They were being created implicitly by `CreateNamespace=true`, which produces a namespace with no labels — fail-open to Cilium and inadmissible to Gatekeeper. Removing that sync option on 2026-08-29 turned a silent wrong into a loud failure; this fixes it properly.

### Added — validation at render time, not only in CI
The chart itself `fail`s on a missing or invalid `class`, `segment`, `team`, `customer`, `podSecurity` or quota tier, and on a `productLine` set on a non-SaaS namespace or missing from a SaaS one. Because it is in the template rather than a lint script, a bad entry fails in ArgoCD too.

### Added — every namespace against the live policy
`scripts/validate.py` renders all entries and evaluates them against the **enforcing** constraints in `aj-cluster-baseline` at HEAD, not a vendored copy. Blocking violations fail; `dryrun` findings are reported and never fatal — a validator stricter than the cluster it models gets switched off.
