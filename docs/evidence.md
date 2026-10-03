# Evidence and community reports

Fixture tests establish behavior on known inputs. Live reports are contributor claims.
Neither authenticates a bank response, proves a unique human, or certifies settlement.
Signed model inference would not prove the truth of its browser inputs.

## Report format

A report records exactly what was tested. Save it as
`banks/<country>/<bank>/reports/YYYY-MM-DD-<reporter-handle-lowercase>.json` (add a
`-<suffix>` before `.json` for a second report the same day):

```json
{
  "schemaVersion": "1",
  "provider": "us/mercury",
  "adapterRevision": "FULL_40_CHARACTER_COMMIT_SHA",
  "harnessRevision": "FULL_40_CHARACTER_COMMIT_SHA",
  "testedAt": "2026-09-23T00:00:00Z",
  "reporter": "YOUR_GITHUB_HANDLE",
  "surface": "web-transactions-lite",
  "capability": "outgoing-domestic-usd-wire",
  "outcome": "partial",
  "evidenceClass": "contributor-live",
  "fixtureRefs": ["fixtures/sent.synthetic.json"],
  "limitations": ["One account; no independent source attestation"],
  "summary": "State what ran and what remains untested, without banking data."
}
```

| Field | Rule |
| --- | --- |
| `provider` | The bank folder ID, equal to the manifest `id`. |
| `adapterRevision` | Full SHA of the commit whose adapter you ran. It must be in the branch's history and contain the bank's `manifest.json` and `transformer.js`. |
| `harnessRevision` | Full SHA of the repository tooling you ran it with (`npm run try:bank` or `npm run bundle:bank`). When you run from a clean checkout, both revisions are the same commit; `try:bank` prints it with `revisionClean`. |
| `testedAt` | UTC time of the live run, not in the future. |
| `reporter` | Your public GitHub handle; the file name ends with it in lowercase. |
| `surface` | Exactly the manifest `surface`. |
| `capability` | Kebab-case payment type you tested, e.g. `outgoing-domestic-usd-wire`. |
| `outcome` | `pass`, `fail`, `partial`, `blocked` or `not-tested`. |
| `evidenceClass` | `contributor-live`, `reviewer-live` or `fixture-only`. Fixture-only reports never count as live reproductions. |
| `fixtureRefs` | Existing `fixtures/<case>.<provenance>.json` files that cover the tested case. |
| `limitations` | At least one honest limitation. |
| `summary` | At most 2,000 characters, no banking data or transcripts. |

`npm run validate` enforces these rules and rejects unknown fields.

Validation also prints advisory warnings when an adapter has no live report or its
manifest/transformer differs from the revision cited by a live report. Historical
reports remain valid records of earlier attempts; a newer report is not required just
to edit documentation or add tests. Missing live evidence does not fail the experimental
adapter checks. Maintainers still apply the issue's acceptance criteria and inspect the
observed source shape, outcome and limitations. These warnings do not authenticate a
response or turn a self-reported pass into verified compatibility.

## Revisions and merging

Create the report after the tested commit exists; a commit cannot contain its own SHA.
Commit the adapter, run the live check on that clean commit, then commit the report citing
it. After that, update the branch with a merge from `main`, not a rebase. Maintainers merge
a PR that adds such a report with **Create a merge commit**: squash and rebase merges rewrite
the cited SHA, and `npm run validate` on `main` would then fail. A report may also cite an
adapter commit already on `main` in a separate PR.

A maintainer checks that the PR author is the reporting handle or explains attribution;
JSON alone cannot prove authorship.

## How reports are aggregated

`npm run catalog` groups reports by adapter revision, harness revision, surface and
capability. Within each scope it shows each public handle's latest outcome, preserving all
original reports. No automatic carry-forward between versions. A ten-handle milestone is not
ten independent people and does not trigger rewards. Read dates, failures and limitations,
not just counts. Counts are submitted reports, not measured population success rates.

## Identity and status semantics

Payer and payee identifiers need explicit schemes and provenance. A display name or memo is
not a verified identity. A sender's `sent` status is not recipient credit. Cross-bank
duplicate prevention and irreversible settlement require separate evidence and policy;
`matchPayment` can compare identifier schemes and a UTC time window, but replay protection
remains the adopting service's job.
