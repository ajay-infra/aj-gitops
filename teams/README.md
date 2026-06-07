# teams/

One directory per team. One YAML file per application (service).

The `workload-apps` ApplicationSet reads all `teams/*/*.yaml` files and generates
one ArgoCD Application per (cluster, team-app) pair automatically.

## How to onboard a team

1. Create `teams/<team-slug>/<app-name>.yaml` for each service
2. Open PR → CI validates YAML
3. Merge → ArgoCD picks up within ~30s on dev/staging clusters
4. Run `register-namespace.yml` to create the AppProject for the team

## File schema

```yaml
# teams/<team>/<app>.yaml
team: team-a                                           # team slug — matches label taxonomy
namespace: team-a                                      # K8s namespace (must match AppProject)
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
