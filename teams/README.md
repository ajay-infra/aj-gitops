# teams/

One directory per team. Two file types per team directory:

| File | Read by | Purpose |
|---|---|---|
| `namespace.yaml` | `namespace-onboarding` AppSet | Provisions namespace + labels + quota + RBAC on every cluster |
| `<app-name>.yaml` | `workload-apps` AppSet | Deploys that app's Helm chart on every matching cluster |

## How to onboard a team

1. Create `teams/<team>/namespace.yaml` — provisions the namespace on every cluster
2. Create `teams/<team>/<app>.yaml` for each service — deploys app workloads
3. Open PR → CI validates YAML
4. Merge → ArgoCD picks up both within ~30s on dev/staging clusters
5. Run `register-namespace.yml` to create the AppProject (ArgoCD UI RBAC)

## namespace.yaml schema

```yaml
# teams/<team>/namespace.yaml — ONE per team (not per app)
namespace: team-a       # K8s namespace name
team: team-a            # team slug — matches label taxonomy
githubTeam: team-a      # GitHub team name within ajay-infra org
model: internal         # internal | saas-pooled | saas-dedicated
customer: ""            # empty for internal namespaces
```

What this provisions on every registered workload cluster:
- Namespace with full label taxonomy (team, env, model, customer, managed-by)
- ResourceQuota sized to environment (dev/staging/prod have different limits)
- LimitRange with safe CPU/memory defaults (prevents unbounded containers)
- Role + RoleBinding: `ajay-infra:<githubTeam>` group gets deployer permissions
- NetworkPolicy: default-deny + allow same-namespace + allow DNS egress

## app.yaml schema

```yaml
# teams/<team>/<app-name>.yaml — one per service
team: team-a                                           # team slug — matches label taxonomy
namespace: team-a                                      # K8s namespace (must match namespace.yaml)
app: api-server                                        # service name — must be unique within namespace
repoURL: https://github.com/ajay-infra/team-a-services # team's GitHub repo
helmPath: helm/api-server                              # path to Helm chart in team repo
```

## Team repo structure expected

```
<team-repo>/
├── apps.yaml                        # for register-namespace.yml workflow (can differ from gitops files)
├── helm/<app>/                      # Helm chart
│   ├── Chart.yaml
│   ├── values.yaml                  # chart defaults
│   └── templates/
├── deployments/<app>/
│   └── values.yaml                  # base overrides (image, replicas, resource requests)
└── environments/
    ├── dev/<app>.yaml               # env-specific overrides
    ├── staging/<app>.yaml
    └── prod/<app>.yaml
```

Value file layering (last wins): chart defaults → deployments → environments/<env>

## Required namespace labels

Every namespace must have these labels (enforced by OPA Gatekeeper):
```yaml
team: <team-slug>
env: dev | staging | uat | prod
model: internal
customer: ""
managed-by: argocd
```

Add these to your namespace definition or let register-namespace.yml create the namespace.
