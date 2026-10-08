---
bank: Shinhan Bank
country: KR
currency: KRW
slug: kr_shinhan
title: "Shinhan Bank — KRW / KR: banking transcripts"
status: planned
website: https://www.shinhan.com
created: 2025-07-11
updated: 2025-07-11
---

# Shinhan Bank — KRW / KR: banking transcripts

## Status
**Planned — not accepting transcripts yet.**

## Reward
- **Planned reward:** $5 USDC per accepted transcript
- **Pilot budget:** $50 total (first-come, first-served up to 10 slots)
- **Target contributors:** 1–5 distinct contributors per bank
- **Payment:** One paid transcript per contributor/account in a campaign

## Scope
- Read-only transaction history
- Relevant existing transaction details
- KRW-denominated accounts in South Korea

## Availability
The published release must be approved and the service must accept your reservation. The pilot has a $50 total reward budget; these planned rates do not mean every bank is funded.

Your local agent discovers the bank flow. PeerLink's attested enclave re-fetches permitted bank responses, extracts a redacted structural artifact, grades it using your inference API key, and pays the fixed reward when the campaign's acceptance rules pass. Peer builds the integration from that evidence; you do not need to write a provider or open a PR.

## How It Works
1. Start with [the contributor skill](https://github.com/zkp2p/peer-link/blob/main/skills/contribute-transcript/SKILL.md), [release status](https://github.com/zkp2p/peer-link/blob/main/transcripts/release.json), and [reward terms](https://github.com/zkp2p/peer-link/blob/main/docs/incentives.md).
2. Your local agent discovers the bank flow.
3. PeerLink's attested enclave re-fetches permitted bank responses, extracts a redacted structural artifact, grades it using your inference API key, and pays the fixed reward when the campaign's acceptance rules pass.
4. Peer builds the integration from that evidence; you do not need to write a provider or open a PR.
5. You pay for model inference, including rejected submissions. Peer pays accepted rewards and payout gas.
6. The approved provider/model, privacy mode, limits and reward must be shown before you consent.
7. The pilot sends only the validated redacted structural artifact to the inference provider; bank credentials are never model prompt text.
8. Confidential NEAR mode is not yet available.

## Rules
- Start with [the contributor skill](https://github.com/zkp2p/peer-link/blob/main/skills/contribute-transcript/SKILL.md), [release status](https://github.com/zkp2p/peer-link/blob/main/transcripts/release.json), and [reward terms](https://github.com/zkp2p/peer-link/blob/main/docs/incentives.md).
- Do not claim a slot by commenting. Reservations happen in the service once this bank opens.
- Comments here are for questions and public endpoint patterns only.
- **Never post tokens, cookies, account IDs, HAR files, screenshots of bank records, or raw transcripts.**

## Migration Note
The old provider-PR program is retired. Prior earned, accepted, or still-valid assigned commitments remain governed by their original terms; this migration does not retroactively reduce them. Previous issue terms are preserved in the migration archive comment below.
