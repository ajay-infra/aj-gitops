# Changelog

All notable changes to this repo are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Fixed
- `.github/workflows/ci.yml`'s `yaml-lint` and `validate-k8s` jobs both referenced a `cloudability/` directory that has never existed in this repo — reproduced locally: `yamllint` fails immediately with `[Errno 2] No such file or directory: 'cloudability/'`, exit code 255. This broke CI on every single PR to this repo, unconditionally, regardless of what the PR actually changed. Removed the `cloudability/` reference from both commands until that TODO (see below) is actually done.
- `CLAUDE.md`'s "Known TODOs" listed "Add `.sops.yaml` and SOPS-encrypted ExternalSecret values" as fully open — `.sops.yaml` already exists. The framing was also confused: ExternalSecrets don't hold secret material client-side (they hold a `remoteRef.key` pointing at a Secrets Manager ARN), so there's nothing in them for SOPS to encrypt. Corrected the TODO to describe what's actually still open: real KMS key ARNs in `.sops.yaml` (currently `REPLACE_WITH_*` placeholders) and real Secrets Manager ARNs in `external-secrets/*.yaml` (same placeholder pattern).
- No `skills.md` existed at all — added one, describing the repo layout, CI checks, and cross-repo dependencies (`aj-tf-module-scps` for KMS ARNs, `aj-tf-module-aurora`/`aj-tf-module-valkey` for Secrets Manager ARNs, `aj-tf-module-ecr` for pull-through cache prefixes). Without it, the `add-opa-policy` skill and any freeform `infra-developer` change here had no repo-context source per the farm's two-source context model.

## [Unreleased, pre-existing]
No prior releases — this repo isn't consumed as a versioned Terraform module by anything (pure GitOps manifests, synced directly from `main`), so there's no tagging convention to follow here unlike the `aj-tf-module-*` repos.
