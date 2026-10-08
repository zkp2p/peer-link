# Incentives

## Overview

PeerLink compensates contributors for verified banking transcript artifacts used to train its regional financial models.

## Reward Structure

### Per-Transcript Rewards

| Bank | Country | Currency | Reward | Status |
|------|---------|----------|--------|--------|
| Chase | US | USD | $5 USDC | ✅ Active |
| Shinhan Bank | KR | KRW | $5 USDC | 📋 Planned |

### Payment Terms

- **Reward:** Fixed USDC payment per accepted transcript
- **Campaign:** One paid transcript per contributor/account per bank campaign
- **Budget:** Pilot budgets are limited; not all banks are immediately funded
- **Gas:** Peer covers payout gas fees for accepted submissions

## How It Works

1. **Discovery:** Your local agent discovers the bank flow via [the contributor skill](../skills/contribute-transcript/SKILL.md)
2. **Collection:** PeerLink's attested enclave re-fetches permitted bank responses and extracts a redacted structural artifact
3. **Grading:** The artifact is graded using your inference API key
4. **Consent:** The approved provider/model, privacy mode, limits and reward are shown before you consent
5. **Payment:** Peer pays accepted rewards and payout gas; you pay for model inference (including rejected submissions)

## Important Notes

- **Never post tokens, cookies, account IDs, HAR files, screenshots of bank records, or raw transcripts** in any public forum
- Do not claim a slot by commenting on GitHub issues
- Reservations happen through the service, not through issue comments
- The old provider-PR program is **retired** — prior earned, accepted, or still-valid commitments remain governed by their original terms

## Privacy

- Only the validated redacted structural artifact is sent to the inference provider
- Bank credentials are never model prompt text
- Confidential NEAR mode is not yet available

## Migration

The old provider-PR program is retired. Prior earned, accepted, or still-valid assigned commitments remain governed by their original terms; this migration does not retroactively reduce them. Previous issue terms are preserved in the migration archive comment below.
