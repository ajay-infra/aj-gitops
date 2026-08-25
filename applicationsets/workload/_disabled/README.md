# Disabled ApplicationSets

Files here are inert. `bootstrap/*.yaml`'s `bootstrap-workload-platform` Application
syncs `applicationsets/workload/` as a plain directory source with no
`directory.recurse` set — ArgoCD does not descend into subdirectories by default, so
nothing in `_disabled/` is ever applied to any cluster.

## Why these three are here

`arc-controller.yaml`, `gatekeeper.yaml`, and `falcon.yaml` each reference
`$values/charts/<name>/values/{{env}}.yaml` — but `charts/arc-controller/`,
`charts/gatekeeper/`, and `charts/falcon/` don't exist anywhere in this repo. If any
of these had stayed in `applicationsets/workload/`, the moment a workload cluster
registered with ArgoCD, all three would go into a permanent sync error (missing Helm
`valueFiles` source).

Moved here on 2026-08-24 rather than deleted, so the design work isn't lost and
re-enabling is a two-step process: add the real `charts/<name>/values/<env>.yaml`
files (real config decisions, not fabricated ones — Falcon needs a real CrowdStrike
CID/secret, ARC needs a real GitHub App's credentials, Gatekeeper needs a real OPA
policy stance), then `git mv` the file back up to `applicationsets/workload/`.

See `CLAUDE.md`'s Known Gaps section for full detail on each.
