# skills.md — aj-platform-gitops

## Purpose
GitOps source of truth for the central cluster platform layer and workload-cluster
add-ons: Helm values for ArgoCD, LGTM stack, k8s-monitoring/Alloy, Argo Rollouts, plus
ApplicationSets that deploy them. No Terraform, no team application manifests (those
live in team repos or `aj-cluster-baseline`).

## Type
`gitops-config`

## Repo layout
See `CLAUDE.md`'s "Repo Layout" section — kept in sync there since it changes often.
Two things worth knowing up front:
- `charts/<name>/values/<env>.yaml` — Helm values only, no `Chart.yaml`/`templates/`.
  ArgoCD multi-source Applications pull the chart from its upstream repo and values
  from here (`ref: values`).
- Not every ApplicationSet in `applicationsets/workload/` has matching values —
  `arc-controller`, `gatekeeper`, `falcon` reference `charts/<name>/values/` paths
  that don't exist. See `CLAUDE.md` Known Gaps before touching any of these three.

## Key ApplicationSet pattern
```yaml
generators:
  - clusters:
      selector:
        matchLabels: { tier: workload }
      values:
        env: "{{metadata.labels.environment}}"
        autoSync: "{{metadata.labels.auto_sync}}"
template:
  spec:
    sources:
      - repoURL: <upstream chart repo>
        chart: <chart>
        helm:
          valueFiles: ["$values/charts/<name>/values/{{values.env}}.yaml"]
      - repoURL: https://github.com/ajay-infra/aj-gitops
        targetRevision: main
        ref: values
```
Cluster labels (`tier`, `environment`, `auto_sync`) come from the cluster Secret that
`provision-eks.yml`'s `argocd-register` stage creates — not from this repo.

## Depends on
`aj-infra-release/provision-eks.yml` (`argocd-register` stage) — creates the cluster
Secret with the labels every workload ApplicationSet generator filters on. Nothing in
this repo can deploy to a cluster that hasn't been registered this way.

## AWS tags applied
None — no Terraform, nothing here creates AWS resources directly. S3 bucket names for
Loki/Mimir/Tempo are injected via ApplicationSet `parameters:` from Terraform outputs,
not set in this repo's values files.

## Branching convention
- `main` — active development, ArgoCD/bootstrap workflows read directly from here
- No tags — not consumed as a versioned module by anything

## CI checks
`ci.yml`: helm lint, yamllint, kubeconform, helm template diff. `bootstrap-argocd.yml`
and `install-argo-rollouts.yml` are `workflow_dispatch` only — ArgoCD and Argo Rollouts
are deliberately installed outside ArgoCD's own management (avoids self-disruption
during upgrades).

## Agentic capabilities
- Detect an ApplicationSet whose `valueFiles` path has no matching file in `charts/` (caught 3 of these already — see Known Gaps in CLAUDE.md)
- Cross-check `onboard-saas-customer`'s expected `saas/` structure exists before that skill is next run (it currently doesn't — see Known Gaps)
- Validate new workload ApplicationSets use the `tier: workload` cluster generator, not a hardcoded cluster list
- Flag Helm chart version drift between the "Helm Chart Versions (pinned)" table in CLAUDE.md and each ApplicationSet's actual `targetRevision`
