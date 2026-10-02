<!-- One bank per PR. Funded work: keep the "Closes" line so the issue links to this PR. -->
Closes #

## Capability and evidence

Bank / country / surface / payment type:
What does "A paid B" mean here, and which facts remain unproven?
Live report: `banks/<country>/<bank>/reports/<file>.json` citing commit:

## Contributor and agent checklist

- [ ] I was assigned to the funded issue (or this is unpaid work) and I may submit this original code and data under MIT.
- [ ] Only `banks/<country>/<bank>/` changed (plus at most its logo, `BANK-ASSETS.md` and regenerated `app/public/catalog.json`).
- [ ] No credentials, cookies, headers, raw responses or HARs, real names, account or transaction IDs, screenshots or transcripts, in any commit.
- [ ] Fixtures are labeled synthetic or sanitized; expected outputs were derived from the bank record, not from the parser.
- [ ] Negative tests cover wrong payer/payee, amount/currency errors, nonfinal/unknown status, missing identifiers, malformed input, duplicate selection and untrusted memo text.
- [ ] `npm run check` (or `npm run check:bank`) passes.
- [ ] `npm run privacy -- --staged` and `npm run privacy -- --range origin/main..HEAD` pass, and I read the full diff.
- [ ] The live report states the exact revision, outcome and limitations, and claims no unique humans, cryptographic source proof or finality.

## Reviewer

Semantic review, remaining limitations and the funded issue's acceptance criteria. If this PR adds a report citing one of its own commits, merge with **Create a merge commit**. Merging requests no payout; acceptance is recorded on the issue.
