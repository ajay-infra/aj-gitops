# Policy tests

```bash
gator verify policies/tests/suite.yaml      # ~0.03s, no cluster needed
```

`brew install gator` if you don't have it. CI runs this on every PR
(`policy-tests` job).

## What these prove, and what they don't

Every policy is tested in **both** directions — a compliant object must produce
no violations, and a specific breach must produce one. A suite that only tests
the deny path can't tell a working rule from one that denies everything.

They were **mutation-checked**: each of the six templates was broken in turn and
the suite failed every time. Reintroducing the real 2026-08-25 PDB bug fails
`partial-label-overlap-does-not-count-as-covered` by name.

**They do not prove Gatekeeper actually enforces any of this in a cluster.**
`gator` evaluates the Rego directly; it never runs an admission webhook. To
close that gap for $0, see
[`aj-infra-context/local-testing/local-verification.md`](https://github.com/ajay-infra/aj-infra-context/blob/main/local-testing/local-verification.md)
— step 2 stands up a `kind` cluster with Gatekeeper and these exact policies, so
you can watch a real admission rejection.

> Expect `allowed-registries` to behave surprisingly there: it pins the literal
> placeholder `555555555555.dkr.ecr.us-east-1.amazonaws.com`, so in a
> live cluster it denies every image whose registry isn't that literal string.

## Adding a case

Fixtures live in `samples/`. A new policy needs at least one allow case and one
deny case, and the deny case should target the branch a naive implementation
would miss — an `initContainer` rather than a `container`, a pod-level field
rather than a container one, an excluded namespace rather than a matched one.
