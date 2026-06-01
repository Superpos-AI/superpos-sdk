# TASK-255: Novps registry credential setup runbook

> **NOTE (updated):** Registry credentials are now provided inline via
> the `NOVPS_IMAGE_CREDENTIALS` env var and sent per-payload as
> `source.credentials` in the apply request to NoVPS. This replaces
> the earlier project-level credential model. The current runbook is
> [novps-pat-setup.md](../runbooks/novps-pat-setup.md), which covers
> both NoVPS API token setup and inline image credential configuration
> (including GHCR PAT). See that runbook's §4 for details.

**Status:** pending (runbook — no code)
**Branch:** `task/255-novps-registry-credential-runbook`
**PR:** —
**Depends on:** —
**Blocks:** TASK-230
**Edition:** cloud (ops)
**Feature doc:** [FEATURE_HOSTED_AGENTS.md](../features/list-1/FEATURE_HOSTED_AGENTS.md) §4.1

## Objective

Document the manual one-time steps to register a private GHCR credential
inside the novps.io project that Superpos Cloud uses, so
`ResourceImageType.credentials` in deploy payloads resolves correctly.
Output: a short runbook in `docs/runbooks/novps-registry-credential.md`.

## Requirements

### Functional

- [ ] FR-1: Document how to provision a GitHub PAT or fine-grained token
  scoped to `read:packages` for `ghcr.io/apiary-ai/*`. Include
  cost / rotation notes (recommend fine-grained, 90-day rotation).
- [ ] FR-2: Document how to register the credential in novps — via the
  novps dashboard or their `/registry/keys` project endpoint — and how
  to capture the returned credential UUID.
- [ ] FR-3: Document the environment variable to set:
  `NOVPS_GHCR_CREDENTIAL_ID=<uuid>` on the Cloud Superpos deployment.
- [ ] FR-4: Document a sanity-check procedure: deploy the `claude-sdk`
  preset into a test hive and confirm pod reaches `running`.
- [ ] FR-5: Document rotation procedure: register new credential →
  update env → redeploy all hosted agents (single bulk op). Include a
  SQL snippet to list affected rows.
- [ ] FR-6: Runbook lives at `docs/runbooks/novps-registry-credential.md`
  and is linked from FEATURE_HOSTED_AGENTS.md §4.1.

### Non-Functional

- [ ] NFR-1: Written as numbered steps with expected output per step.
- [ ] NFR-2: Includes "if something breaks" section pointing at the two
  most likely failure modes (bad token scope, rate limit on GHCR).

## Test Plan

- [ ] Dry-run: ops engineer follows the runbook against a staging
  novps project and provisioned a working credential end-to-end.
- [ ] Rotation procedure verified by swapping to a new credential and
  redeploying a test hosted agent.

## Validation Checklist

- [ ] Runbook committed
- [ ] Link added to FEATURE_HOSTED_AGENTS.md §4.1
- [ ] No secrets in the runbook (only placeholders)
