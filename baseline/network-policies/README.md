# Network policies

`CiliumNetworkPolicy` expressing the tiers in
`aj-infra-context/arch/network-segmentation.md` §3.

## Read this before adding a default-deny

**These are ALLOW rules, and enforcement is not yet switched on.**

Cilium is installed with no `policyEnforcementMode` set, which means default
behaviour: an endpoint is unrestricted *until some policy selects it*. So the
moment a policy below selects a pod, that pod becomes deny-by-default for the
direction the policy covers.

That is the whole hazard. **Order is not a style preference:**

```
1. label        namespaces and pods carry platform.aj/segment
2. allow        write these policies, covering every real flow
3. observe      Hubble — confirm nothing legitimate is being dropped
4. deny         only then, policyEnforcementMode: always
```

Reversed, the cluster stops serving traffic and the cause is invisible unless
you already have Hubble open.

## Selection

Rules key on `io.kubernetes.pod.namespace`, which Cilium adds to every endpoint
automatically. That is deliberate: it works without every workload author
remembering to label their pods, and it cannot be bypassed by omitting a label.

Namespace → tier:

| tier | namespaces |
|---|---|
| `edge` | `apisix` |
| `platform` | `opa`, `cert-manager`, `external-secrets`, `external-dns`, `kube-system`, `monitoring`, `argocd`, `falcon-system` |
| `app` | `frontend`, `backend`, `llm`, `search` |
| `data` | `data-access` |

## Not covered yet

- **DNS and the K8s API** are allowed explicitly in each policy. They are the
  two things that break first under default-deny and the two most often
  forgotten.
- **Cross-cluster** is out of scope — see `network-segmentation.md` §5. The recurring
  legitimate flow is workload → central, which crosses VPCs rather than pods.
- **Egress to the data subnets** is a CIDR rule in `data.yaml`, and the CIDR is
  a placeholder until the data layer exists.
