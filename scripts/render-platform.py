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

      argocd  the ArgoCD install itself. It is declared TWICE in this estate:
                - aj-infra-central/argocd.tf         helm_release, values there
                - .github/workflows/bootstrap-argocd.yml   helm upgrade --install
              Both are rendered and compared, because they do not agree.

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
import difflib
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


def argocd_version_from_workflow(repo_root):
    """ARGOCD_CHART_VERSION out of bootstrap-argocd.yml — the file that installs it."""
    wf = repo_root / ".github/workflows/bootstrap-argocd.yml"
    doc = load_yaml(wf)
    version = doc.get("env", {}).get("ARGOCD_CHART_VERSION")
    repo = doc.get("env", {}).get("ARGOCD_CHART_REPO")
    if not version or not repo:
        raise Failure(f"{wf}: ARGOCD_CHART_VERSION / ARGOCD_CHART_REPO not found")
    return str(version), repo


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
    """Both declarations of the ArgoCD install, per hub."""
    renders = []
    wf_version, wf_repo = argocd_version_from_workflow(repo_root)

    for cls, tier in hubs:
        # 1. What bootstrap-argocd.yml installs. Note the values path carries no
        #    class — one file per tier, shared by both hubs.
        values = repo_root / f"charts/argocd/values/{tier}.yaml"
        if values.is_file():
            renders.append(Render(
                stack="argocd",
                hub=f"{cls}/{tier}",
                name="argocd (bootstrap-argocd.yml)",
                chart="argo-cd",
                repo=wf_repo,
                version=wf_version,
                namespace="argocd",
                release="argocd",
                values_files=[values],
                sets=[],
                source=".github/workflows/bootstrap-argocd.yml",
            ))

        # 2. What aj-infra-central/argocd.tf installs, if that repo is present.
        if central_root is not None:
            tf_values = central_root / f"helm-values/argocd/{cls}-{tier}.yaml"
            if tf_values.is_file():
                renders.append(Render(
                    stack="argocd",
                    hub=f"{cls}/{tier}",
                    name="argocd (aj-infra-central)",
                    chart="argo-cd",
                    repo="https://argoproj.github.io/argo-helm",
                    version=argocd_version_from_central(central_root),
                    namespace="argocd",
                    release="argo-cd",
                    values_files=[tf_values],
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

    argocd = [r for r in renders if r.stack == "argocd"]
    if argocd:
        add("## Argo stack")
        add("")
        if central_root is None:
            add("> `aj-infra-central` was not checked out, so only the "
                "`bootstrap-argocd.yml` declaration is rendered.")
            add("")
        add("| Hub | Declared by | Release | Chart | Values | Manifests |")
        add("|---|---|---|---|---|---:|")
        for r in argocd:
            values = ", ".join(str(p).split("/")[-1] for p in r.values_files)
            status = "" if not r.problems else " ⚠️"
            add(f"| `{r.hub}` | `{r.source}`{status} | `{r.release}` | "
                f"`{r.chart}` {r.version} | `{values}` | {r.manifests} |")
        add("")
        add(comparison(argocd))

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


def comparison(argocd_renders):
    """The two ArgoCD declarations, per hub, against each other."""
    out = ["### The two declarations, compared", ""]
    by_hub = {}
    for r in argocd_renders:
        by_hub.setdefault(r.hub, []).append(r)

    any_pair = False
    for hub, pair in sorted(by_hub.items()):
        if len(pair) != 2 or any(r.out is None for r in pair):
            continue
        any_pair = True
        a, b = pair
        left = a.out.read_text().splitlines()
        right = b.out.read_text().splitlines()
        differing = sum(1 for line in difflib.unified_diff(left, right, n=0)
                        if line.startswith(("+", "-"))
                        and not line.startswith(("+++", "---")))
        names_a = {(d.get("kind"), d.get("metadata", {}).get("name"))
                   for d in yaml.safe_load_all(a.out.read_text()) if d}
        names_b = {(d.get("kind"), d.get("metadata", {}).get("name"))
                   for d in yaml.safe_load_all(b.out.read_text()) if d}
        only_a = sorted(f"{k}/{n}" for k, n in names_a - names_b)
        only_b = sorted(f"{k}/{n}" for k, n in names_b - names_a)

        out.append(f"**`{hub}`** — release `{a.release}` vs `{b.release}`, "
                   f"{differing} differing lines.")
        if only_a:
            out.append(f"- only in `{a.source}`: {', '.join(f'`{x}`' for x in only_a[:8])}")
        if only_b:
            out.append(f"- only in `{b.source}`: {', '.join(f'`{x}`' for x in only_b[:8])}")
        if differing == 0:
            out.append("- byte-identical output")
        elif not only_a and not only_b:
            out.append("- same resources, different contents")
        out.append("")

    if not any_pair:
        return ""
    out.append("Two declarations of one install, under two release names. "
               "Installing via one and then the other produces two releases, "
               "not an upgrade.")
    out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", default=".", type=Path)
    ap.add_argument("--central-root", type=Path, default=None,
                    help="path to an aj-infra-central checkout (public repo)")
    ap.add_argument("--out", default="out/dry-run", type=Path)
    ap.add_argument("--summary", type=Path, default=None,
                    help="write the markdown report here (e.g. $GITHUB_STEP_SUMMARY)")
    ap.add_argument("--stack", choices=["lgtm", "argocd", "all"], default="all")
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

    renders = []
    try:
        if args.stack in ("lgtm", "all"):
            for path in appsets:
                cls, tier = path.parent.parent.name, path.parent.name
                renders += parse_lgtm(path, cls, tier, repo_root)
        if args.stack in ("argocd", "all"):
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

    report = markdown(renders, args.kube_version, central_root, out_dir)
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
