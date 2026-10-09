# Contribute a Banking Transcript

## Overview

This skill guides you through the process of contributing a redacted banking transcript to PeerLink. By providing transaction history data, you help expand PeerLink's financial data coverage for inference and analytics purposes.

## Rewards

Rewards are defined per-provider in the [incentives documentation](../../../docs/incentives.md) and tracked in [`transcripts/release.json`](../../../transcripts/release.json). Each accepted transcript pays a fixed USDC reward once the campaign acceptance rules pass.

## Eligibility

- You must have an active PeerLink account with attested enclave access.
- You may contribute **one transcript per bank account** per campaign.
- The bank must be listed as **planned** or **open** in the release tracker.
- You must consent to the approved provider, privacy mode, limits, and reward before starting.

## How to Contribute

### Step 1: Check Release Status

View the current release status:

```bash
curl -s https://api.github.com/repos/zkp2p/peer-link/contents/transcripts/release.json | base64 -d
```

Look for your bank under `providers`. A status of `planned` means the campaign is not yet accepting submissions. An `open` status means you can reserve a slot.

### Step 2: Reserve a Slot

Once the bank is `open`, reserve your slot through the PeerLink service dashboard. No public comments or claims on GitHub issues reserve a slot — reservations happen exclusively in the service.

### Step 3: Collect Your Transcript

1. Log into your bank account through the provider's official app or web portal.
2. Export or screenshot your transaction history for the requested date range.
3. **Never** post raw credentials, tokens, cookies, account IDs, HAR files, screenshots of bank records, or unredacted transcripts in any public forum.

### Step 4: Redact and Submit

Your local agent will:
- Re-fetch permitted bank responses through the attested enclave.
- Extract a **redacted structural artifact** — removing all personally identifiable information (PII).
- Grade the artifact using your inference API key.
- Submit only the validated redacted structural artifact to the inference provider.

**Bank credentials are never part of the model prompt text.**

### Step 5: Receive Reward

If the campaign acceptance rules pass:
- Peer pays the fixed reward in USDC.
- Payout gas is covered by Peer.
- You bear the cost of model inference, including rejected submissions.

## Privacy Guarantees

- Only the redacted structural artifact is sent to the inference provider.
- Confidential NEAR mode is **not yet available**.
- Your bank credentials and account identifiers are never exposed.

## Supported Banks

See [`transcripts/release.json`](../../../transcripts/release.json) for the full list of banks, their status, and reward amounts.

## Current Providers

| Bank | Country | Currency | Status | Reward (USDC) |
|------|---------|----------|--------|---------------|
| easypaisa | PK | PKR | planned | 5 |

## Important Notes

- The old provider-PR program is **retired**. Do not submit PRs to add providers — Peer builds integrations from accepted evidence.
- Comments on issue pages are for questions and public endpoint patterns only.
- Prior commitments remain governed by their original terms.

## Troubleshooting

- **Bank not showing as open**: Check the release tracker; the campaign may not have funded its reward pool yet.
- **Submission rejected**: Review the redaction guidelines; ensure no PII remains in the artifact.
- **Reward not received**: Verify your slot was accepted and the enclave attestation passed.

## Links

- [Release Tracker](../../../transcripts/release.json)
- [Incentive Terms](../../../docs/incentives.md)
- [Contribution Skill](./SKILL.md)
