---
name: test-bank
description: Reproduce an existing Peer Link bank adapter against an account owner's authorized session and submit a revision-specific, privacy-safe report. Use for live reports on new adapters and independent reproductions.
---

# Test a bank adapter

A report records what one account owner observed when one exact adapter revision ran on
their own bank response. It is evidence for review, not proof of source authenticity,
recipient credit or a unique person. Failures and partial results are as useful as passes.

Read [AGENTS.md](../../AGENTS.md), [docs/privacy.md](../../docs/privacy.md),
[docs/evidence.md](../../docs/evidence.md) and the provider's `README.md` first.

## 1. Pick the exact revision

Test a commit that already contains the adapter: `main` for a merged adapter, or the
contributor's committed branch head for a new one. Start from a clean tree.

```sh
git fetch origin && git checkout <commit-or-branch>
npm ci --ignore-scripts
npm test -- banks/<country>/<bank>    # fixture tests must pass before live testing
git status --porcelain                 # must print nothing
```

## 2. Capture one response locally

The account owner signs in normally (including MFA) and opens an existing transaction of the
adapter's supported type. Do not create, edit or cancel payments. Save the JSON response the
page loaded, exactly as the provider README describes, to `.local/<bank>-response.json`:

- Browser-capable agents: use your network-inspection tool to read the response body of the
  request the page made. Do not replay requests or copy cookies or headers.
- Manual: DevTools > Network > Fetch/XHR > select the request > Response > copy and save.

If the response is missing, has changed shape, or needs a request the README does not
describe, stop and report `blocked` with the reason. That is an acquisition result, not a
parser failure.

## 3. Run the adapter

```sh
npm run try:bank -- <country>/<bank> .local/<bank>-response.json <transactionId>
```

The output contains a redacted summary and `revision`/`revisionClean`. The owner compares
outcome, masked payer and payee, amount, currency, status and timestamp with the bank's own
UI. If you can also select a transaction the adapter must reject (pending, other type), run
it and confirm it abstains. Agents working inside the bank tab can instead run
`npm run bundle:bank -- <country>/<bank>`, evaluate the generated `.local/` harness in the
page, and call `PeerLinkHarness.run(response, transactionId)`.

Delete `.local/<bank>-response.json` when finished. Never paste the response, the summary,
screenshots or transcripts into GitHub.

## 4. Write and submit the report

Create `banks/<country>/<bank>/reports/YYYY-MM-DD-<your-handle-lowercase>.json`:

```json
{
  "schemaVersion": "1",
  "provider": "<country>/<bank>",
  "adapterRevision": "<full revision from try:bank>",
  "harnessRevision": "<same full revision>",
  "testedAt": "2026-10-02T12:00:00Z",
  "reporter": "<your-github-handle>",
  "surface": "<manifest surface>",
  "capability": "<kebab-case payment type>",
  "outcome": "pass",
  "evidenceClass": "contributor-live",
  "fixtureRefs": ["fixtures/<case>.synthetic.json"],
  "limitations": ["One account, one transaction; source authenticity not established."],
  "summary": "What ran and what matched or failed, without banking data."
}
```

- `outcome`: `pass` only if every compared field matched; `partial`, `fail`, `blocked` or
  `not-tested` otherwise. Explain which fields in `summary` without values.
- `evidenceClass`: `contributor-live` for your own account, `reviewer-live` for a
  maintainer reproduction, `fixture-only` if you only ran fixtures.
- If a parser defect appears, add a synthetic regression fixture in a separate PR.

```sh
npm run validate
npm run privacy -- --staged
npm run privacy -- --range origin/main..HEAD
```

Open a PR that adds only the report (or include it in the adapter PR, per
[contribute-bank](../contribute-bank/SKILL.md)). Do not rebase after the report is
committed; the cited revision must stay in history. A reporting handle is a self-report, not
a verified unique account.
