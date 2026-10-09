# Contribute a banking transcript

The paid contribution is authenticated, redacted banking evidence from your own
account. Peer engineers build the integration. You do not implement a provider,
claim an issue by commenting, or open a provider PR.

**The service is unreleased and currently accepts no bank credentials or paid
contributions.** Check the [release manifest](transcripts/release.json),
[verification guide](docs/verification.md), and bank campaign before continuing.
A campaign is usable only with an approved independently verified release, active
source policy, available slots and reserved rewards.

The single [Merit project profile](https://terminal.merit.systems/zkp2p/peer-link) points to PeerLink
for discovery. Bank-specific rewards and enrollment remain in PeerLink campaign
issues; contributors do not claim separate Merit bounties. The next launch candidate
is Wise only, up to two $5 contributions, conditional on approved release and
reserved funds. Other banks remain planned.

## Entry point

Give your local agent the prompt in [README.md](README.md), then follow
[skills/contribute-transcript/SKILL.md](skills/contribute-transcript/SKILL.md).
Read [privacy](docs/privacy.md) and [reward terms](docs/incentives.md) first.

1. Find your bank's existing campaign issue. It publishes a fixed $5 or $10 USDC
   reward, scope, access status, limits and remaining capacity. One issue covers
   the bank; an issue listing alone does not promise funding or readiness.
2. Confirm your own account access and choose the approved model/provider,
   privacy consent and payout address. You fund inference, even when rejected.
   Check costs and capacity before gathering a session.
3. Sign in and complete MFA yourself. Your agent records the read-only history
   route and relevant existing transaction details. No payment or account changes.
4. Reserve the bounded job. Independently verify fresh Nitro attestation, the
   approved measured release, policy and encryption key before encrypting your
   session, recipe and inference key directly to the enclave.
5. The enclave acquires fresh bank evidence and redacts it before inference.
   Code checks authenticity, coverage, duplicates and budget. If accepted under
   an enabled campaign, the service sends the fixed reward once and returns a receipt.
6. Revoke the inference key and use your bank's logout/session controls afterwards.
   Never post captures, secrets or banking records to GitHub or chat.

A bank seeks 1–5 distinct contributors, with at most one paid contribution per
contributor/account per campaign. New wallets or GitHub accounts do not establish
new contributors. Confidential NEAR mode is not available in the current pilot.

## Requests, bugs and repository maintenance

Propose a bank only if it has no existing campaign issue, using the bank-request
template. Report public fixed reason codes and redacted structural failures using
the failure template. Send vulnerabilities or exposures through [SECURITY.md](SECURITY.md).
Never attach raw captures, identifiers, screenshots, API keys or request headers.

Service, documentation and synthetic regression fixes remain normal code maintenance;
they do not earn a transcript reward. Keep changes focused and original, run the
relevant credential-free checks, inspect the complete diff, and run:

```sh
npm run privacy -- --staged
npm run privacy -- --range origin/main..HEAD
```

Existing adapter tooling and its CI layout checks remain for reference assets.
Maintainer-reviewed service/layout changes have their own scope; do not treat the
old bank-folder procedure as a prerequisite for transcript contributions.
Synthetic fixtures must use invented values, not copied bank records.

## Legacy contributions

The old provider program is retired. See its
[archived contribution guide](https://github.com/zkp2p/peer-link/blob/31bba0e6c55f41ff08f31d30e728e1ef41d38a3b/CONTRIBUTING.md) and
[archived award terms](https://github.com/zkp2p/peer-link/blob/31bba0e6c55f41ff08f31d30e728e1ef41d38a3b/docs/incentives.md) for historical context.
Legacy PRs may close with a program-change notice while their commits and
conversations remain available. Previously earned or accepted awards are preserved;
disputed earlier claims require review under the original written terms.
Do not reinterpret a legacy obligation using the new $5/$10 campaign rules.

Code contributions require rights to submit under MIT. Do not copy proprietary,
employer-owned or private Peer implementation code. Acceptance of evidence or code
does not enable a bank in Peer or certify settlement.
