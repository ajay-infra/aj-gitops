# aj-namespace-registry

The living configuration of every **workload and tenant** namespace in the
estate. One small YAML per namespace; a Helm chart renders it into a
`Namespace`, a `ResourceQuota` and a `LimitRange`.

```yaml
# registry/all-workload/frontend.yaml
namespace: frontend

identity:
  team:     product
  class:    product
  customer: internal
  segment:  app

guardrails:
  podSecurity: restricted
  quota:       medium
```

## Why a registry rather than namespace manifests

**The label set becomes template-enforced instead of discipline-enforced.**

Before this repo, a namespace's labels were whatever whoever wrote the YAML
remembered. That produced two failures in one week: `falcon-system` nearly lost
its Pod Security labels when its ownership moved between repos, and eleven
platform namespaces were created by Helm with no labels at all — leaving them
fail-open to Cilium and inadmissible to Gatekeeper.

A registry entry cannot forget a label. The chart fails to render if `segment`,
`customer`, `class` or `team` is missing or wrong, with a message saying what
the field is *for*:

```
identity.segment "frontend" must be one of [edge platform app data] — it
selects the CiliumNetworkPolicy, and an endpoint no policy selects is
UNRESTRICTED
```

## The check that makes it worth having

`scripts/validate.py` renders **every** entry and runs it through the **real**
Gatekeeper constraints from `aj-cluster-baseline` — not a vendored copy, the
enforcing ones at HEAD. Every namespace in the estate is checked against live
policy on every PR.

It separates violations that **would block admission** from those reported by
constraints in `dryrun`. A validator stricter than the cluster it models gets
switched off, so `dryrun` findings are printed and never fatal.

```
5 namespace(s) against 11 constraints (2 in dryrun)

reported (5, dryrun — would NOT block admission):
  ... require-product-code ... has team 'product', which is not a product code

PASS — nothing that would block admission
```

## Placement is a directory, not a field

`registry/all-workload/` lands on every cluster labelled `tier=workload`. Future
scopes get their own directory and their own ApplicationSet.

This is a mechanism constraint, not a preference: an ApplicationSet matrix
generator produces the cross-product of clusters and files, and cannot filter it
by a field *inside* the file. Encoding placement in the path is what works;
encoding it in the entry would read better and silently place namespaces
everywhere.

## Scope

**Workload and tenant namespaces only.** Platform namespaces
(`cert-manager`, `karpenter`, `apisix`, …) are declared in
`aj-infra-platform/namespaces.tf`, because Terraform's `helm_release` installs
into a namespace that must already exist — and ArgoCD cannot create it first,
since the cluster is not registered with ArgoCD until after the platform apply.

That split disappears if add-on installation ever moves to ArgoCD
(`aj-infra-platform#15`). Until then it is a real ordering constraint, not a
preference.

## Adding a namespace

1. Add a file under the right `registry/<scope>/` directory
2. Open a PR — CI renders it and runs it against live policy
3. Merge; ArgoCD reconciles

There is no step where anyone writes a label.
