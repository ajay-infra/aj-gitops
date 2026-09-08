#!/usr/bin/env python3
"""
Render every platform install this repo performs — offline, no cluster, no AWS.

WHAT THIS IS
    ArgoCD's repo-server renders a Helm source by running `helm template` with
    the Application's valueFiles and parameters. This does the same thing, from
    the same files, so what it writes is what the hub would apply.

    Two stacks:

      lgtm    applicationsets/central/<class>/<tier>/lgtm.yaml
              grafana, loki, mimir, tempo — one Application per component, per
              hub. Four hubs, sixteen renders.

      argocd  the ArgoCD install itself, declared once — aj-infra-central's
              `helm_release.argocd`, values in that repo. This repo used to
              carry a second installer under a different release name, so the
              two were parallel installs rather than one; that is gone, and
              this renders what is left.

WHAT THIS IS NOT
    Not `terraform plan`. aj-infra-central reads live infrastructure at plan
    time (aws_eks_cluster, aws_caller_identity, terraform_remote_state) and
    cannot plan offline. The AWS half of argocd.tf — the IAM role, the ksops
    KMS policy, the pod identity association — is NOT covered here. Nothing in
    this script substitutes for that.

    Not admission control. No cluster means no webhooks, no CRD presence check,
    no `lookup()`, and `.Capabilities.APIVersions` holds only what
    --kube-version implies.

    Values that live on the ArgoCD cluster Secret cannot be read from git, so
    they are MOCKED. Every mock is printed beside the value it produced.

CHECKS THAT CAN FAIL
    1. any `helm template` that errors
    2. a bucket name that does not match aj-infra-central's `name_prefix`
       ("central-<class>-<tier>") — a bucket Terraform never creates
    3. a parameter that renders to nothing: the AppSet sets
       loki.storage.bucketNames.chunks and image.repository by PATH, and a
       wrong path is silent. Both are asserted to appear in the output.

Usage:
    scripts/render-platform.py --out out/dry-run [--summary $GITHUB_STEP_SUMMARY]
    scripts/render-platform.py --stack lgtm --hub product/prod
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

# ── Mocks ────────────────────────────────────────────────────────────────────
# Stage 1 has no AWS account. These stand in for values ArgoCD would read off
# the cluster Secret at render time. They are marked MOCK everywhere they show.
MOCK_ECR_REGISTRY = "555555555555.dkr.ecr.us-east-1.amazonaws.com"

# k8s_version in aj-infra/envs/central/<class>/<tier>/eks.tfvars — all four
# hubs are on 1.35 as of 2026-09-07. Duplicated here because aj-infra is
# private and this workflow cannot read it; --kube-version overrides.
DEFAULT_KUBE_VERSION = "1.35"

# aj-infra-central/locals.tf:  name_prefix = "central-${class}-${tier}"
BUCKET_PREFIX = "central-{cls}-{tier}"

TEMPLATE_VAR = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


# Renders that cannot succeed yet, and why. Self-expiring: if one of these
# starts rendering, this script FAILS and names the entry to delete. An
# exemption list without a staleness check outlives the thing it excused —
# TRANSITIONAL in aj-infra's check-workflows.py rotted within the hour.
#
# Every entry here is a real dependency, not a rendering quirk. The first two
# are the strongest argument in the estate for provisioning ECR: those
# ApplicationSets pull their CHARTS, not just their images, through a registry
# that does not exist — so they would fail on a real cluster exactly as they
# fail here.
BLOCKED = {
    "arc-runners": "chart is oci:// in the ECR registry, which nothing creates yet",
    "gateway-api-crds": "chart is oci:// in the ECR registry, which nothing creates yet",
    "cloudability": "chart repo https://apptio.github.io/apptio-cloudability-helm-charts "
                    "returns 404 — the repository has moved or gone, and the "
                    "replacement URL is not known. Verified 2026-09-07.",
}


class Failure(Exception):
    pass


def load_yaml(path):
    with open(path) as fh:
        return yaml.safe_load(fh)


def expand(value, ctx, where):
    """Substitute {{key}} against ctx. An unknown key is an error, not a blank."""
    if not isinstance(value, str):
        return value

    def sub(match):
        key = match.group(1)
        if key not in ctx:
            raise Failure(f"{where}: no value for {{{{{key}}}}}")
        return str(ctx[key])

    return TEMPLATE_VAR.sub(sub, value)


class Render:
    """One `helm template` invocation and everything needed to judge it."""

    def __init__(self, stack, hub, name, chart, repo, version, namespace,
                 release, values_files, sets, source, expect=()):
        self.stack = stack
        self.hub = hub
        self.name = name
        self.chart = chart
        self.repo = repo
        self.version = version
        self.namespace = namespace
        self.release = release
        self.values_files = values_files
        self.sets = sets            # list of (key, value)
        self.source = source        # human description of what declares this
        self.expect = list(expect)  # (label, string that must appear) pairs
        self.out = None
        self.manifests = 0
        self.kinds = {}
        self.images = []
        self.problems = []


def load_clusters(repo_root):
    """The declared ArgoCD cluster Secrets under clusters/**.

    These are what every generator in this repo selects on. Until they existed,
    the generators matched nothing and this script had to invent the values it
    could not read.
    """
    out = []
    base = repo_root / "clusters"
    if not base.is_dir():
        return out
    for f in sorted(base.rglob("*.yaml")):
        doc = load_yaml(f)
        if not doc or doc.get("kind") != "Secret":
            continue
        meta = doc.get("metadata") or {}
        labels = meta.get("labels") or {}
        if labels.get("argocd.argoproj.io/secret-type") != "cluster":
            continue
        data = doc.get("stringData") or {}
        out.append({
            "file": f,
            "name": data.get("name") or meta.get("name"),
            "server": data.get("server", ""),
            "labels": labels,
            "annotations": meta.get("annotations") or {},
        })
    return out


def selector_matches(selector, cluster):
    want = (selector or {}).get("matchLabels") or {}
    return all(cluster["labels"].get(k) == v for k, v in want.items())


def generator_context(gen, cluster):
    """Resolve a clusters generator's `values:` block against one cluster.

    `{{metadata.labels.environment}}` and `{{metadata.annotations.ecr_registry}}`
    are read off the Secret rather than mocked — which is the whole point of
    declaring it.
    """
    ctx = {"name": cluster["name"], "server": cluster["server"]}
    for key, template in ((gen.get("values") or {}).items()):
        value = str(template)
        for m in TEMPLATE_VAR.finditer(str(template)):
            path = m.group(1)
            if path.startswith("metadata.labels."):
                value = value.replace(m.group(0), cluster["labels"].get(path.split(".", 2)[2], ""))
            elif path.startswith("metadata.annotations."):
                value = value.replace(m.group(0), cluster["annotations"].get(path.split(".", 2)[2], ""))
        ctx[f"values.{key}"] = value
    return ctx


def parse_workload(path, cls, clusters, repo_root):
    """One workload ApplicationSet, rendered once per cluster it selects.

    Returns (renders, skipped) — skipped carries a reason, because an
    ApplicationSet this cannot render must show up in the report rather than
    silently not appearing in it.
    """
    doc = load_yaml(path)
    if not doc or doc.get("kind") != "ApplicationSet":
        return [], [(path.name, "not an ApplicationSet")]
    spec = doc["spec"]

    gens = spec["generators"]
    if not (len(gens) == 1 and "clusters" in gens[0]):
        return [], [(path.name, "generator is not a plain clusters generator")]
    gen = gens[0]["clusters"]

    template = spec["template"]["spec"]
    sources = template.get("sources") or ([template["source"]] if "source" in template else [])
    chart_src = next((x for x in sources if "chart" in x), None)
    if chart_src is None:
        kind = "path" if any("path" in x for x in sources) else "unknown"
        return [], [(path.name, f"{kind} source — needs a directory render, not helm template")]

    renders = []
    for cluster in clusters:
        if not selector_matches(gen.get("selector"), cluster):
            continue
        ctx = generator_context(gen, cluster)
        where = f"{path} [{cluster['name']}]"
        helm = chart_src.get("helm", {})
        release = expand(helm.get("releaseName", path.stem), ctx, where)
        namespace = expand(str(template["destination"]["namespace"]), ctx, where)

        values_files = []
        for vf in helm.get("valueFiles", []):
            local = expand(vf, ctx, where).replace("$values/", "")
            full = repo_root / local
            if full.is_file():
                values_files.append(full)
            elif not helm.get("ignoreMissingValueFiles"):
                raise Failure(f"{where}: valueFile {local} does not exist and "
                              f"ignoreMissingValueFiles is not set")

        sets, expect = [], []
        for param in helm.get("parameters", []):
            key = expand(str(param["name"]), ctx, where)
            val = expand(str(param["value"]), ctx, where)
            if key == "":
                continue
            sets.append((key, val))
            expect.append((key, val))

        renders.append(Render(
            stack="workload",
            hub=f"{cls}/{cluster['name']}",
            name=path.stem,
            chart=chart_src["chart"],
            repo=expand(str(chart_src["repoURL"]), ctx, where),
            version=str(chart_src["targetRevision"]),
            namespace=namespace,
            release=release,
            values_files=values_files,
            sets=sets,
            source=str(path),
            expect=expect,
        ))
    return renders, []


def parse_lgtm(path, cls, tier, repo_root):
    """Read one hub's LGTM ApplicationSet into a list of Render."""
    doc = load_yaml(path)
    spec = doc["spec"]

    matrix = None
    for gen in spec["generators"]:
        if "matrix" in gen:
            matrix = gen["matrix"]["generators"]
    if matrix is None:
        raise Failure(f"{path}: expected a matrix generator")

    cluster_gen = next((g["clusters"] for g in matrix if "clusters" in g), None)
    list_gen = next((g["list"] for g in matrix if "list" in g), None)
    if cluster_gen is None or list_gen is None:
        raise Failure(f"{path}: expected clusters x list generators")

    # `env` comes from the cluster Secret's environment label. The selector
    # pins that label, so this is resolved, not mocked.
    labels = cluster_gen.get("selector", {}).get("matchLabels", {})
    env = labels.get("environment")
    if env is None:
        raise Failure(f"{path}: clusters selector does not pin `environment`")

    values_ctx = {
        "values.env": env,
        "values.ecr_registry": MOCK_ECR_REGISTRY,
        "values.autoSync": "false",  # sync policy only — never reaches helm
    }

    template = spec["template"]["spec"]
    sources = template["sources"]
    chart_src = next(s for s in sources if "chart" in s)

    renders = []
    for element in list_gen["elements"]:
        ctx = dict(values_ctx)
        ctx.update({k: v for k, v in element.items()})
        where = f"{path} [{element.get('component')}]"

        helm = chart_src.get("helm", {})
        release = expand(helm.get("releaseName", "{{component}}"), ctx, where)
        namespace = expand(template["destination"]["namespace"], ctx, where)

        values_files = []
        for vf in helm.get("valueFiles", []):
            # $values/<path> — the ref source is this repo.
            local = expand(vf, ctx, where).replace("$values/", "")
            full = repo_root / local
            if not full.is_file():
                raise Failure(f"{where}: valueFile {local} does not exist")
            values_files.append(full)

        sets, expect = [], []
        for param in helm.get("parameters", []):
            key = expand(param["name"], ctx, where)
            val = expand(param["value"], ctx, where)
            if key == "":
                # Verified against helm 3.16.3: `--set =x` is accepted and is a
                # no-op. Grafana has no bucket, and the matrix carries an empty
                # s3BucketParam for it rather than a second list element.
                continue
            sets.append((key, val))
            expect.append((key, val))

        renders.append(Render(
            stack="lgtm",
            hub=f"{cls}/{tier}",
            name=element["component"],
            chart=element["chart"],
            repo=expand(element["repoURL"], ctx, where),
            version=str(element["version"]),
            namespace=namespace,
            release=release,
            values_files=values_files,
            sets=sets,
            source=str(path),
            expect=expect,
        ))
    return renders


def argocd_version_from_central(central_root):
    """The `chart_version_argocd` default in aj-infra-central/variables.tf.

    The real value comes from aj-infra/envs/central/<class>/<tier>/central.tfvars,
    which is in a private repo this workflow cannot read. The variable default
    tracks it today; when they diverge, this reports the default and says so.
    """
    text = (central_root / "variables.tf").read_text()
    match = re.search(
        r'variable\s+"chart_version_argocd"\s*\{[^}]*?default\s*=\s*"([^"]+)"',
        text, re.S)
    if not match:
        raise Failure("aj-infra-central/variables.tf: no default for chart_version_argocd")
    return match.group(1)


def parse_argocd(repo_root, central_root, hubs):
    """The ArgoCD install, per hub. One declaration: aj-infra-central."""
    if central_root is None:
        return []
    renders = []
    version = argocd_version_from_central(central_root)
    for cls, tier in hubs:
        values = central_root / f"helm-values/argocd/{cls}-{tier}.yaml"
        if not values.is_file():
            raise Failure(f"aj-infra-central has no helm-values/argocd/{cls}-{tier}.yaml")
        renders.append(Render(
            stack="argocd",
            hub=f"{cls}/{tier}",
            name="argocd",
            chart="argo-cd",
            repo="https://argoproj.github.io/argo-helm",
            version=version,
            namespace="argocd",
            release="argocd",
            values_files=[values],
            sets=[],
            source="aj-infra-central/argocd.tf",
        ))
    return renders


def run_helm(render, helm_bin, kube_version, out_dir):
    cmd = [
        helm_bin, "template", render.release, render.chart,
        "--repo", render.repo,
        "--version", render.version,
        "--namespace", render.namespace,
        "--kube-version", kube_version,
        "--include-crds",
    ]
    for vf in render.values_files:
        cmd += ["-f", str(vf)]
    for key, val in render.sets:
        cmd += ["--set", f"{key}={val}"]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        render.problems.append("helm template failed:\n" + proc.stderr.strip())
        return

    # The name must be unique per render, not per component: the two ArgoCD
    # declarations are both called "argocd" and the first version of this
    # collapsed them onto one file, which then compared identical to itself.
    slug = re.sub(r"[^a-z0-9]+", "-",
                  f"{render.hub}-{render.name}".lower()).strip("-")
    path = out_dir / render.stack / f"{slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(proc.stdout)
    render.out = path

    docs = [d for d in yaml.safe_load_all(proc.stdout) if d]
    render.manifests = len(docs)
    for doc in docs:
        kind = doc.get("kind", "?")
        render.kinds[kind] = render.kinds.get(kind, 0) + 1
    render.images = sorted({
        m for m in re.findall(r"^\s*image:\s*\"?([^\"\s]+)", proc.stdout, re.M)
    })

    # A parameter set by path is silent when the path is wrong. Prove each one
    # reached the output.
    for key, val in render.expect:
        if val not in proc.stdout:
            render.problems.append(
                f"parameter `{key}={val}` does not appear in the rendered output — "
                f"the path is wrong for {render.chart} {render.version}, and the "
                f"override is being silently dropped")


def check_buckets(render, cls, tier):
    expected_prefix = BUCKET_PREFIX.format(cls=cls, tier=tier)
    for key, val in render.sets:
        if "bucket" not in key.lower():
            continue
        if not val.startswith(expected_prefix + "-"):
            render.problems.append(
                f"bucket `{val}` does not match aj-infra-central's name_prefix "
                f"`{expected_prefix}` — Terraform creates "
                f"`{expected_prefix}-<suffix>`, so this points at a bucket that "
                f"does not exist")


def markdown(renders, kube_version, central_root, out_dir):
    lines = []
    add = lines.append
    add("# Platform dry run")
    add("")
    add(f"Rendered with `helm template`, Kubernetes `{kube_version}`, no cluster "
        f"and no AWS. Manifests are in the **rendered-manifests** artifact.")
    add("")

    lgtm = [r for r in renders if r.stack == "lgtm"]
    if lgtm:
        add("## LGTM stack")
        add("")
        add("What each hub's ApplicationSet hands to ArgoCD, component by component.")
        add("")
        add("| Hub | Component | Chart | Values | Manifests | Parameters ArgoCD sets |")
        add("|---|---|---|---|---:|---|")
        for r in lgtm:
            # Every parameter, not a guess at which one is the interesting one:
            # the parameter names differ per chart and a "which key looks like
            # an image" heuristic reported tempo as having no image override
            # when it has one under `tempo.repository`.
            params = "<br>".join(
                f"`{k}` = `{v.replace(MOCK_ECR_REGISTRY, '<MOCK ecr>')}`"
                for k, v in r.sets) or "—"
            values = ", ".join(p.name for p in r.values_files) or "—"
            status = "" if not r.problems else " ⚠️"
            add(f"| `{r.hub}` | {r.name}{status} | `{r.chart}` {r.version} | "
                f"`{values}` | {r.manifests} | {params} |")
        add("")
        add(f"`<MOCK ecr>` = `{MOCK_ECR_REGISTRY}` — the ECR registry is an "
            f"annotation on the ArgoCD cluster Secret, which does not exist in git.")
        add("")

    workload = [r for r in renders if r.stack == "workload"]
    if workload:
        add("## Workload add-ons")
        add("")
        add("Rendered per cluster, from the declared cluster Secrets in "
            "`clusters/**` — the labels these ApplicationSets select on.")
        add("")
        add("| Cluster | Add-on | Chart | Values | Manifests | Parameters |")
        add("|---|---|---|---|---|---:|---|".replace("|---:|---|", "---:|---|"))
        for r in workload:
            params = "<br>".join(
                f"`{k}` = `{v.replace(MOCK_ECR_REGISTRY, '<MOCK ecr>')}`"
                for k, v in r.sets) or "—"
            values = ", ".join(p.name for p in r.values_files) or "chart defaults"
            status = "" if not r.problems else " ⚠️"
            add(f"| `{r.hub}` | {r.name}{status} | `{r.chart}` {r.version} | "
                f"`{values}` | {r.manifests} | {params} |")
        add("")

    argocd = [r for r in renders if r.stack == "argocd"]
    if argocd:
        add("## Argo stack")
        add("")
        add("Declared once, by `aj-infra-central/argocd.tf`. This repo holds "
            "what ArgoCD deploys, never what installs it.")
        add("")
        add("| Hub | Declared by | Release | Chart | Values | Manifests |")
        add("|---|---|---|---|---|---:|")
        for r in argocd:
            values = ", ".join(str(p).split("/")[-1] for p in r.values_files)
            status = "" if not r.problems else " ⚠️"
            add(f"| `{r.hub}` | `{r.source}`{status} | `{r.release}` | "
                f"`{r.chart}` {r.version} | `{values}` | {r.manifests} |")
        add("")

    add("## What this does not cover")
    add("")
    add("- **Not a `terraform plan`.** `aj-infra-central` reads live "
        "infrastructure at plan time, so the AWS half of `argocd.tf` — IAM "
        "role, ksops KMS policy, pod identity association — is not rendered "
        "here by anything.")
    add("- **No admission control**: no webhooks, no CRD presence check, no "
        "`lookup()`. `.Capabilities.APIVersions` holds only what "
        f"`--kube-version {kube_version}` implies.")
    add("- **No cluster Secret**, so ArgoCD's cluster generator is resolved "
        "from the ApplicationSet's own selector and the ECR registry is mocked.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", default=".", type=Path)
    ap.add_argument("--central-root", type=Path, default=None,
                    help="path to an aj-infra-central checkout (public repo)")
    ap.add_argument("--out", default="out/dry-run", type=Path)
    ap.add_argument("--summary", type=Path, default=None,
                    help="write the markdown report here (e.g. $GITHUB_STEP_SUMMARY)")
    ap.add_argument("--stack", default="all",
                    choices=["lgtm", "argocd", "workload", "central", "all"],
                    help="`central` is lgtm+argocd — the two hub stacks — so a "
                         "per-hub CI leg does not also re-render the whole "
                         "workload tree once per tier")
    ap.add_argument("--hub", action="append", default=None,
                    help="restrict to <class>/<tier>; repeatable")
    ap.add_argument("--helm", default="helm")
    ap.add_argument("--kube-version", default=DEFAULT_KUBE_VERSION)
    args = ap.parse_args()

    repo_root = args.repo_root.resolve()
    central_root = args.central_root.resolve() if args.central_root else None
    if central_root is not None and not central_root.is_dir():
        print(f"::warning::--central-root {central_root} is not a directory; "
              f"rendering the bootstrap-argocd.yml declaration only")
        central_root = None

    appsets = sorted((repo_root / "applicationsets/central").glob("*/*/lgtm.yaml"))
    if not appsets:
        print("::error::no applicationsets/central/*/*/lgtm.yaml found — refusing "
              "to report success on an empty search")
        return 1

    hubs = [(p.parent.parent.name, p.parent.name) for p in appsets]
    if args.hub:
        wanted = set(args.hub)
        hubs = [h for h in hubs if f"{h[0]}/{h[1]}" in wanted]
        appsets = [p for p in appsets
                   if f"{p.parent.parent.name}/{p.parent.name}" in wanted]
        if not hubs:
            print(f"::error::--hub matched nothing; have "
                  f"{[f'{c}/{t}' for c, t in [(p.parent.parent.name, p.parent.name) for p in appsets]]}")
            return 1

    clusters = load_clusters(repo_root)
    if not clusters:
        print("::warning::no cluster Secrets under clusters/** — workload "
              "ApplicationSets select on labels that then exist nowhere")

    renders, skipped = [], []
    try:
        if args.stack in ("workload", "all"):
            for cls in sorted({c for c, _ in hubs}):
                for appset in sorted((repo_root / "applicationsets/workload" / cls).glob("*.yaml")):
                    got, miss = parse_workload(appset, cls, clusters, repo_root)
                    renders += got
                    skipped += miss
        if args.stack in ("lgtm", "central", "all"):
            for path in appsets:
                cls, tier = path.parent.parent.name, path.parent.name
                renders += parse_lgtm(path, cls, tier, repo_root)
        if args.stack in ("argocd", "central", "all"):
            renders += parse_argocd(repo_root, central_root, hubs)
    except Failure as exc:
        print(f"::error::{exc}")
        return 1

    if not renders:
        print("::error::nothing to render")
        return 1

    out_dir = args.out.resolve()
    for render in renders:
        print(f"→ {render.hub:16} {render.stack:6} {render.name:28} "
              f"{render.chart}@{render.version}")
        run_helm(render, args.helm, args.kube_version, out_dir)
        if render.stack == "lgtm":
            cls, tier = render.hub.split("/")
            check_buckets(render, cls, tier)

    # Blocked renders are expected to fail; a blocked render that SUCCEEDS is
    # the staleness signal.
    blocked_hits = []
    for render in renders:
        if render.name not in BLOCKED:
            continue
        if render.problems:
            blocked_hits.append((render.name, BLOCKED[render.name]))
            render.problems = []
        else:
            render.problems = [
                f"BLOCKED lists this as unrenderable ({BLOCKED[render.name]}), "
                f"but it rendered — delete the entry"]

    report = markdown(renders, args.kube_version, central_root, out_dir)
    if blocked_hits:
        lines = ["", "### Blocked", "",
                 "Expected to fail, and failing for the recorded reason. This "
                 "list fails the check if one of them starts working.", ""]
        for name, why in sorted(set(blocked_hits)):
            lines.append(f"- `{name}` — {why}")
        lines.append("")
        report += "\n" + "\n".join(lines)
    if skipped:
        lines = ["", "### Not rendered", "",
                 "These ApplicationSets are real and are not covered by this "
                 "check. Listed rather than omitted, so the report cannot be "
                 "read as coverage it does not have.", ""]
        for name, why in skipped:
            lines.append(f"- `{name}` — {why}")
        lines.append("")
        report += "\n" + "\n".join(lines)
    print()
    print(report)
    if args.summary:
        with open(args.summary, "a") as fh:
            fh.write(report + "\n")

    failed = [r for r in renders if r.problems]
    if failed:
        print()
        print("## Problems", file=sys.stderr)
        for r in failed:
            for problem in r.problems:
                print(f"::error::{r.hub} {r.name}: {problem}")
        print(f"\n{len(failed)} of {len(renders)} renders have problems.",
              file=sys.stderr)
        return 1

    print(f"\n{len(renders)} renders, "
          f"{sum(r.manifests for r in renders)} manifests, no problems.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
