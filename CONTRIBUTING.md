# Contributing to Peer Link

Peer Link accepts one kind of code contribution: a bank adapter folder that interprets one
payment type from one bank surface, with synthetic fixtures, negative tests, documentation
and a privacy-safe live report. Fixes to existing adapters, fixtures and docs are welcome too.

Read [docs/privacy.md](docs/privacy.md) before collecting any bank data.

## Fastest path: give your coding agent this prompt

> Read AGENTS.md and skills/contribute-bank/SKILL.md in https://github.com/zkp2p/peer-link.
> Help me contribute my bank's payment integration (issue #<number> if there is one). Keep
> raw captures and credentials local. Do not initiate payments.

The [contribute-bank skill](skills/contribute-bank/SKILL.md) is the complete runbook, from
claiming an issue to opening the PR. Use the [test-bank skill](skills/test-bank/SKILL.md) to
reproduce an existing adapter and the [review skill](skills/review-contribution/SKILL.md) to
review one. More context: [docs.peer.xyz/developer/peer-link](https://docs.peer.xyz/developer/peer-link).

## Steps

1. **Pick or propose a bank.** Funded issues carry the `Merit` label and state the amount,
   scope, folder and deadline ([program terms](https://github.com/zkp2p/peer-link/issues/64),
   [incentives](docs/incentives.md)). To propose another bank, open a
   [bank request](https://github.com/zkp2p/peer-link/issues/new?template=bank-request.md).
2. **Claim it.** Comment on the issue with the surface, the one transfer type and
   confirmation that you or a collaborator own an authorized account. Wait for assignment
   before starting paid work. Never post credentials, records or identity documents.
3. **Build it** under `banks/<country>/<bank>/`: `npm run new-bank -- <country>/<bank>`
   creates the required files. Define who A and B are, identity provenance, amount units,
   currency, status, timestamp, transaction-ID scope and unsupported cases. Ambiguous
   evidence must return `insufficient_evidence`.
4. **Test it** with synthetic fixtures whose expected outputs are derived from the bank
   record, negative tests, and one live check by the account owner
   (`npm run try:bank`). Write a report per [docs/evidence.md](docs/evidence.md).
5. **Check it**: `npm run check` (or `npm run check:bank` without Python),
   `npm run privacy -- --staged`, `npm run privacy -- --range origin/main..HEAD` and
   `npm run validate -- --contribution-base origin/main`. Read the whole diff.
6. **Open a PR** using the template. Funded work says `Closes #<issue>`. One bank per PR.
7. **Review and payout.** A maintainer reviews semantics, privacy and tests against the
   issue's written scope. For funded issues, acceptance is recorded on the issue and the
   award is paid through Merit. Complete wallet, tax and payout eligibility directly with
   [Merit](https://terminal.merit.systems/zkp2p/peer-link). Merge, green CI, coverage or AI
   review never trigger payment by themselves.

## What CI accepts

CI runs without bank credentials, secrets or privileged tokens. `npm run validate` rejects:

- files outside the repository layout, such as new top-level files;
- in pull requests from forks, any new file outside `banks/<country>/<bank>/` except that
  bank's logo in `app/public/logos/`;
- bank folders with other file types (screenshots, HAR files, PDFs, helper modules),
  invalid manifests, fixtures or reports, impure transformers, or leftover `TODO`s.

PRs that restate an issue, add generated "solution" files or touch unrelated code are
closed without review. Propose tooling or layout changes in an issue first.

## Licensing and conduct

By contributing you confirm you have the right to submit the code and data under the
project's MIT license. Do not submit employer-owned, proprietary or private Peer
implementation code. No copyright assignment is requested.

Report broken integrations with the failure issue template and security or privacy issues
through [private reporting](SECURITY.md). Maintainer: @0xSachinK. Merging an adapter does
not certify a bank, a payer or settlement finality, and does not enable it in Peer.

## What the automatic checks cover

CI runs layout and privacy checks before adapter tests. It also scans every changed file
version in a pull request, including data removed in a later commit and new content in
merge resolutions. Run `npm run privacy -- --range origin/main..HEAD` before pushing;
the CI scan cannot undo an initial public disclosure. Historical files outside the current
layout receive an advisory review warning, including deleted captures that content rules
may not recognize. A green scan does not certify redaction.

The required `verify` status includes the repository checks and, for fork PRs, checks
using the base branch's tooling. A failed or unexpectedly skipped check blocks that status.
Code-owner review still protects changes to the workflow and shared check definitions.

The shared adapter suite perturbs nested fixture fields to check that malformed input
does not throw or produce an invalid observation. It deliberately does not assume common
field names, status vocabularies, amount units or bank identifier formats. Keep testing
those semantics in your adapter, including missing/negated statuses, masked identifiers,
contradictory currency fields, invalid amount grouping and duplicate selection. Coverage
and green checks do not replace review of an observed bank response.

Missing or stale live reports produce advisory messages, not an automatic rejection of
experimental work. See [evidence](docs/evidence.md) for revision and acceptance boundaries.
