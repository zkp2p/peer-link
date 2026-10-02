# 🔗 Peer Link

**Link your bank, get rewarded for building.**

An MIT-licensed library of bank adapters, payment semantics, privacy-safe fixtures, and community test reports. Bring your bank account and your coding agent. Turn what works for you into knowledge anyone can inspect, reproduce, and maintain.

[Website](https://link.peer.xyz) · [Contribute](CONTRIBUTING.md) · [Integrations](https://link.peer.xyz/#providers) · [Incentives](docs/incentives.md)

**$1,000 in bounties** is funded on [Merit](https://terminal.merit.systems/zkp2p/peer-link) for 20 banks, $50 each, paid in USDC. Pick a bank from the [bounty index](https://github.com/zkp2p/peer-link/issues/64), get assigned on its issue, and follow the [terms](docs/incentives.md). Contributions for any other bank are welcome too.

## Start with your agent

Give your browser-capable coding agent this prompt (add the issue number if your bank has one):

> Read AGENTS.md and skills/contribute-bank/SKILL.md in https://github.com/zkp2p/peer-link. Help me contribute my bank's payment integration. Keep raw captures and credentials local. Do not initiate payments.

The [contribute-bank skill](skills/contribute-bank/SKILL.md) walks the agent from claiming an issue to a pull request: scaffold the adapter, inspect your own session locally, write synthetic fixtures and negative tests, run a redacted live check, and submit a privacy-safe report. No extension is required. Your agent uses its own authorized browser tooling; this repository provides no remote bank access, and you sign into your bank normally. Developer docs: [docs.peer.xyz/developer/peer-link](https://docs.peer.xyz/developer/peer-link).

## Run locally

Node 20.19+ and npm. No secrets or bank account are required for fixture tests.

```sh
git clone https://github.com/zkp2p/peer-link.git
cd peer-link
npm ci --ignore-scripts
npm run check:bank                     # adapter gates: types, lint, coverage, validation, privacy
npm run verify:setup && npm run check  # full CI suite; needs Python 3.11+ and OpenSSL
npm run dev                            # landing page
```

`app/` contains the landing page. `banks/<country>/<bank>/` contains an adapter, manifest, tests, fixtures and reports. `lib/` defines a small shared observation format, not a published SDK.

## What a result means

A parser can tell you what supplied evidence says. It cannot establish that the evidence came from a bank. `supported` means the supported interpretation is present, not that funds should be released. Downstream attestation systems must authenticate evidence and apply their own settlement policy. The verification service is under development; its release manifest currently refuses live secret sharing. No production settlement or automatic payout is enabled.

Community reports are revision-specific claims, not certified unique people or bank accounts. Failures and partial results are useful. Ten reporting handles is a community milestone, not a trust or payout threshold. [Evidence model](docs/evidence.md).

## Agent maintenance and verification

Peer Link is designed for agent-assisted maintenance. Public prompts, explicit policies and machine-readable decisions make reviews inspectable. A private verifier is being built to authenticate bank evidence inside an AWS enclave, with deterministic reference checks and explicit account-owner consent.

**Current status: development, not a live verification service.** No scheduled agent tasks or automatic payouts are enabled.

**Venice remains disabled:** Peer Link has not independently verified its TEE execution and end-to-end response authenticity. Bank data is not forwarded to Venice or OpenAI. The [synthetic agent evaluation](docs/verification.md#synthetic-agent-evaluation) tests the advisory review task only; success does not establish Venice model accuracy or TEE security.

September 23, 2026 validation:

- [Nitro hardware tests](verification/infra/evidence/2026-09-23-nitro-components.json) passed attestation/tampering checks, 16 component tests and four synthetic Mercury Wasm cases.
- [Independent CI builds](verification/infra/evidence/2026-09-23-normalized-builds.json) produce byte-identical unsigned EIFs after informational metadata normalization. Nitro CLI validates their checksums and unchanged PCR0/1/2. A [disposable signed Nitro boot](verification/infra/evidence/2026-09-23-normalized-hardware.json) also passed attestation and tampering checks. A production signing identity and approved public release remain unfinished.
- A [synthetic Venice probe](verification/infra/evidence/2026-09-23-venice-synthetic-protocol.json) reached encrypted inference, but response signature byte binding failed. No bank data was sent.
- The consent handshake and acquisition/oracle/adapter stages have synthetic integration tests. Runtime receipts now have synthetic composition tests. Live bank acquisition and complete hardware flow validation remain release gates.

Run `npm run verify:readiness` for a machine-readable report. It currently exits with status 2 because live verification is unavailable. Passing parser tests or merging a contribution does not enable it.

CI publishes each builder's experimental unsigned `normalized.eif` with its measurements in the `nitro-build-one` and `nitro-build-two` artifacts (retained for seven days). [Download and compare instructions](docs/verification.md#inspect-experimental-ci-binaries). These are inspection artifacts, not approved releases for sharing secrets.

[Architecture and security boundaries](docs/architecture.md) · [Private adoption contract](docs/attestation-adoption.md) · [Verification guide](docs/verification.md) · [Agent contract](verification/agent-contract.json) · [Operator skill](skills/operate-verifier/SKILL.md) · [Release status](verification/release.json)

## Contribute

- Add a bank adapter with meaningful negative tests ([skill](skills/contribute-bank/SKILL.md)).
- Reproduce a provider against your own account and submit a privacy-safe report ([skill](skills/test-bank/SKILL.md)).
- Add an edge case, fix a broken integration or improve acquisition instructions.
- Sponsor a reviewed issue. Only issues labelled `Merit` with a funded amount carry a reward.

[Contribution guide](CONTRIBUTING.md) · [Privacy rules](docs/privacy.md) · [Security](SECURITY.md)

Peer Link is an independent community project. It is not affiliated with, endorsed by, or sponsored by Plaid Inc. or named financial institutions. Bank names identify integrations only.

Copyright (c) 2026 Sachin Kumar and Peer Link contributors. [MIT](LICENSE).
