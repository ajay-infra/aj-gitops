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

    blocking, reporting, rendered = [], [], 0
    for cluster in sorted(by_cluster):
        parts = list(policy_docs)
        for entry in by_cluster[cluster]:
            cls, tenant, _, ns = entry.parts[-5:-1]
            r = run(["helm", "template", ns, str(HERE / "chart"), "-f", str(entry),
                     "--set", f"namespace={ns}", "--set", f"class={cls}",
                     "--set", f"customer={tenant}", "--set", f"cluster={cluster}"])
            if r.returncode != 0:
                print(f"FAIL  {entry.relative_to(HERE)} does not render\n{r.stderr.strip()}")
                return 1
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

    print("\nPASS — nothing that would block admission")
    return 0


if __name__ == "__main__":
    sys.exit(main())
