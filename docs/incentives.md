# Incentive Terms

## Payment Structure

- **Fixed reward per accepted transcript**: Defined per provider in [`transcripts/release.json`](../transcripts/release.json).
- **Reward currency**: USDC on Base (EVM).
- **Payout wallet**: `0x96eE7904BdCd8a82c71B4FFc3362C96b1Aae03e0`

## Current Rewards

| Provider | Country | Currency | Reward (USDC) |
|----------|---------|----------|---------------|
| easypaisa | PK | PKR | 5 |

## Payment Conditions

1. The transcript must pass the campaign's acceptance rules.
2. The contributor must have reserved a valid slot through the PeerLink service.
3. The attested enclave must successfully re-fetch and grade the redacted structural artifact.
4. The payout is sent once the campaign's funding status is confirmed.

## Contributor Responsibilities

- You pay for model inference costs, including rejected submissions.
- You must redact all PII before submission.
- You must not post credentials, tokens, or raw transcripts publicly.

## Peer Responsibilities

- Peer covers payout gas fees.
- Peer pays the fixed reward upon acceptance.
- Peer builds the integration from accepted evidence; no provider PR is required.

## Migration Notice

The old provider-PR program is retired. This migration does not retroactively reduce prior earned, accepted, or still-valid assigned commitments.
