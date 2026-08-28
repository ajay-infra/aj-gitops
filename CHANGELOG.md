# Changelog

All notable changes to this repo are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- **`deny-acm-exportable`** — a ConstraintTemplate + Constraint rejecting any ACK ACM `Certificate` (`acm.services.k8s.aws`) that sets `spec.exportTo`.
  - `exportTo` requests an **exportable** public certificate: **$7 per FQDN and $79 per wildcard, charged at issuance AND at every renewal** on a 198-day validity — roughly **$158/year** per wildcard. Standard ACM certificates are free, and the one case `exportTo` serves (in-cluster TLS termination) is already covered free by cert-manager.
  - **This is admission control because nothing else can do the job.** ACM has no IAM condition key for the export option, and the charge lands at *issuance* rather than at export — so withholding `acm:ExportCertificate` stops the private key leaving but does not stop the bill. Rejecting the object before admission is the only control that prevents the spend, because the controller then never calls `RequestCertificate` with export enabled.
  - **Cluster-wide and unconditional**, unlike the workload constraints which are scoped to prod namespaces. An exportable certificate costs the same in dev, and dev is where someone experimenting would reach for `exportTo` first.
  - Three `gator` cases, in both directions: a certificate without `exportTo` must produce no violations (a constraint that denied everything would silently stop the estate issuing any certificate), and both a plain and a wildcard `exportTo` must be denied — the wildcard case asserting on the cost figure so the message keeps carrying the reason.

### Fixed
- `.github/workflows/ci.yml`'s `yaml-lint` and `validate-k8s` jobs both referenced a `cloudability/` directory that has never existed in this repo — reproduced locally: `yamllint` fails immediately with `[Errno 2] No such file or directory: 'cloudability/'`, exit code 255. This broke CI on every single PR to this repo, unconditionally, regardless of what the PR actually changed. Removed the `cloudability/` reference from both commands until that TODO (see below) is actually done.
- `CLAUDE.md`'s "Known TODOs" listed "Add `.sops.yaml` and SOPS-encrypted ExternalSecret values" as fully open — `.sops.yaml` already exists. The framing was also confused: ExternalSecrets don't hold secret material client-side (they hold a `remoteRef.key` pointing at a Secrets Manager ARN), so there's nothing in them for SOPS to encrypt. Corrected the TODO to describe what's actually still open: real KMS key ARNs in `.sops.yaml` (currently `REPLACE_WITH_*` placeholders) and real Secrets Manager ARNs in `external-secrets/*.yaml` (same placeholder pattern).
- No `skills.md` existed at all — added one, describing the repo layout, CI checks, and cross-repo dependencies (`aj-tf-module-scps` for KMS ARNs, `aj-tf-module-aurora`/`aj-tf-module-valkey` for Secrets Manager ARNs, `aj-tf-module-ecr` for pull-through cache prefixes). Without it, the `add-opa-policy` skill and any freeform `infra-developer` change here had no repo-context source per the farm's two-source context model.

## [Unreleased, pre-existing]
No prior releases — this repo isn't consumed as a versioned Terraform module by anything (pure GitOps manifests, synced directly from `main`), so there's no tagging convention to follow here unlike the `aj-tf-module-*` repos.
