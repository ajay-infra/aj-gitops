#!/usr/bin/env python3
"""Render every registry entry and run it through the REAL Gatekeeper policy.

This is the point of the repo. The label set a namespace needs is defined in one
place (aj-cluster-baseline/policies/) and produced in another (here). Before this
repo existed those two agreed only because somebody remembered — which is how
falcon-system nearly lost its Pod Security labels during a move, and why a gator
sample had to be hand-written to pin the two repos together.

Now every namespace in the estate is checked against the live policy on every
PR, rather than one representative sample.

  Usage: workloads/scripts/validate.py [path-to-baseline]

Since consolidation this reads the constraints from ../baseline in the SAME
repo, so it needs no cross-repo checkout and no credential — the check that
could not run in CI now simply runs.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
REPO = HERE.parent

GROUP_RE = re.compile(r"^team-[0-9]{4}-(read|write)$")
# identity-and-access-v1.md §6.3 — what the write group may bind to, per stage.
# Mirrors chart/values.yaml rbac.writeRoleByStage; a drift between the two is
# exactly what this check exists to catch.
WRITE_ROLE = {"nonprod": "platform-developer", "sandbox": "platform-developer",
              "preprod": "platform-deployer", "prod": "platform-viewer", "prodpciconn": "platform-viewer"}
STRICTEST = "prodpciconn"


def cluster_stages() -> dict:
    """cluster name -> stage, from the cluster Secrets' labels.

    The ApplicationSet passes the Secret's `stage` label to the chart, so the
    Secret is the source here too. A cluster with records but no Secret gets
    STRICTEST: ArgoCD would generate nothing for it, and rendering it as prod
    cannot hide a binding that would be wrong on prod.
    """
    out = {}
    for f in sorted((REPO / "clusters").rglob("*.yaml")):
        text = f.read_text()
        if "argocd.argoproj.io/secret-type: cluster" not in text:
            continue
        name = re.search(r"^\s+name:\s*(\S+)", text, re.M)
        stage = re.search(r"^\s+stage:\s*(\S+)", text, re.M)
        env = re.search(r"^\s+environment:\s*(\S+)", text, re.M)
        if env and stage:
            out[env.group(1)] = stage.group(1)
    return out


def check_rbac(entry: Path, rendered: str, team: str, stage: str, problems: list) -> None:
    """Detector 4 (identity-and-access-v1.md §9): the two RoleBindings the chart
    rendered are the two the design says, and write never exceeds the stage."""
    docs = [d for d in rendered.split("\n---") if "kind: RoleBinding" in d]
    rel = entry.relative_to(HERE)
    if len(docs) != 2:
        problems.append(f"{rel}: {len(docs)} RoleBinding(s) rendered, expected exactly 2 (read, write)")
        return
    seen = {}
    for d in docs:
        subj = re.search(r"kind: Group\n\s+name:\s*(\S+)", d)
        role = re.search(r"kind: ClusterRole\n\s+name:\s*(\S+)", d)
        if not subj or not GROUP_RE.match(subj.group(1)):
            problems.append(f"{rel}: RoleBinding subject {subj.group(1) if subj else '<none>'!r} is not on the group grammar")
            continue
        seen[subj.group(1)] = role.group(1) if role else None
    want = {f"{team}-read": "platform-viewer", f"{team}-write": WRITE_ROLE[stage]}
    if seen != want:
        problems.append(f"{rel} (stage {stage}): bindings are {seen}, expected {want}")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, **kw)


def enforcement_actions(constraints_dir: Path) -> dict:
    """constraint name -> enforcementAction.

    Parsed with a regex rather than a YAML library so this script has no
    dependencies and runs anywhere gator does. Both fields are single-line
    scalars in every constraint here; a mismatch shows up as an unknown
    constraint below rather than a silent pass.
    """
    out = {}
    for f in sorted(constraints_dir.glob("*.yaml")):
        text = f.read_text()
        name = re.search(r"^  name:\s*(\S+)", text, re.M)
        act = re.search(r"^  enforcementAction:\s*(\S+)", text, re.M)
        if name:
            out[name.group(1)] = act.group(1) if act else "deny"
    return out


def main() -> int:
    baseline = Path(sys.argv[1] if len(sys.argv) > 1 else HERE.parent / "baseline")
    policies = baseline / "policies"
    if not policies.is_dir():
        print(f"no policies/ under {baseline}")
        return 1
    for tool in ("helm", "gator"):
        if not shutil.which(tool):
            print(f"{tool} not found on PATH")
            return 1

    actions = enforcement_actions(policies / "constraints")

    # Document separators are NOT optional. Concatenating YAML without them
    # merges documents and gator silently evaluates nothing — a clean PASS
    # meaning the check never ran. Cost an hour on 2026-08-29.
    policy_docs = [f.read_text() for f in
                   sorted((policies / "templates").glob("*.yaml")) +
                   sorted((policies / "constraints").glob("*.yaml"))]

    entries = sorted((HERE / "registry").rglob("namespace.yaml"))
    if not entries:
        print("no registry entries found")
        return 1

    # Grouped BY CLUSTER, and evaluated one cluster at a time.
    #
    # The same namespace name exists on several clusters, which is correct — but
    # feeding them to gator in one stream produces duplicate-resource warnings,
    # and a warning that is always there is a warning nobody reads. One run per
    # cluster also mirrors what actually happens: each cluster admits its own
    # set, independently.
    by_cluster = {}
    for e in entries:
        by_cluster.setdefault(e.parts[-3], []).append(e)

    stages = cluster_stages()
    blocking, reporting, rendered, rbac_problems = [], [], 0, []
    for cluster in sorted(by_cluster):
        stage = stages.get(cluster)
        if stage is None:
            print(f"note  {cluster}: no cluster Secret — rendered as {STRICTEST} (strictest); ArgoCD generates nothing for it")
            stage = STRICTEST
        parts = list(policy_docs)
        for entry in by_cluster[cluster]:
            cls, tenant, _, ns = entry.parts[-5:-1]
            r = run(["helm", "template", ns, str(HERE / "chart"), "-f", str(entry),
                     "--set", f"namespace={ns}", "--set", f"class={cls}",
                     "--set", f"customer={tenant}", "--set", f"cluster={cluster}",
                     "--set", f"stage={stage}"])
            if r.returncode != 0:
                print(f"FAIL  {entry.relative_to(HERE)} does not render\n{r.stderr.strip()}")
                return 1
            team = re.search(r"^team:\s*(\S+)", entry.read_text(), re.M)
            check_rbac(entry, r.stdout, team.group(1) if team else "", stage, rbac_problems)
            parts.append(r.stdout)
            rendered += 1

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write("\n---\n".join(parts))
            combined = fh.name
        r = run(["gator", "test", f"--filename={combined}"])
        for line in (r.stdout + r.stderr).splitlines():
            if not line.strip() or "WARNING" in line:
                continue
            m = re.search(r'\["([^"]+)"\]', line)
            action = actions.get(m.group(1), "deny") if m else "deny"
            (reporting if action == "dryrun" else blocking).append(f"[{cluster}] {line}")

    print(f"{rendered} namespace(s) across {len(by_cluster)} cluster(s), "
          f"{len(actions)} constraints ({sum(1 for a in actions.values() if a == 'dryrun')} in dryrun)")

    if reporting:
        # Reported, never fatal. dryrun means the cluster admits these — a
        # validator stricter than the thing it models gets switched off.
        print(f"\nreported ({len(reporting)}, dryrun — would NOT block admission):")
        for l in reporting[:6]:
            print(f"  {l}")
        if len(reporting) > 6:
            print(f"  … and {len(reporting) - 6} more")

    if blocking:
        print(f"\nFAIL — {len(blocking)} violation(s) that WOULD block admission:")
        for l in blocking:
            print(f"  {l}")
        return 1

    if rbac_problems:
        print(f"\nFAIL — {len(rbac_problems)} RoleBinding(s) not what §6.3 derives:")
        for l in rbac_problems:
            print(f"  {l}")
        return 1

    print("PASS — every namespace renders exactly its two RoleBindings, write never exceeds the stage")
    print("\nPASS — nothing that would block admission")
    return 0


if __name__ == "__main__":
    sys.exit(main())
