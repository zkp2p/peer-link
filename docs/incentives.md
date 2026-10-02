# Bounties

**$1,000 is funded for 20 bank integrations, $50 each, paid in USDC through
[Merit](https://terminal.merit.systems/zkp2p/peer-link).** The
[bounty index (#64)](https://github.com/zkp2p/peer-link/issues/64) is the live
source of truth; each bank issue states its exact scope. There is no token and
no automatic payout.

## Funding — October 2, 2026

Two 500 USDC sponsor deposits on Base (chain 8453) were credited to the
sponsor's Merit account and allocated to the `zkp2p/peer-link` Merit project:
[deposit 1](https://basescan.org/tx/0x53902d363f347e888b63d5266b95da66f9f53ee1fa487331bef583c65ec695c9),
[deposit 2](https://basescan.org/tx/0xbffb6d25d3b95463d3fe5d5a0739701a5d84f3224639eff164361f1fabe26145).
Merit showed **$1,000 funded, $1,000 available and $0 paid out** after the
second allocation. Awards are earmarked from that project pool, not escrowed per
issue. The infrastructure budget for the verifier is separate.

## Funded banks

| Bank | Issue | Currency | Award |
| --- | --- | --- | ---: |
| Monobank | [#6](https://github.com/zkp2p/peer-link/issues/6) | UAH | $50 |
| Vietcombank | [#8](https://github.com/zkp2p/peer-link/issues/8) | VND | $50 |
| Chase | [#73](https://github.com/zkp2p/peer-link/issues/73) | USD | $50 |
| Bank of America | [#74](https://github.com/zkp2p/peer-link/issues/74) | USD | $50 |
| Wells Fargo | [#75](https://github.com/zkp2p/peer-link/issues/75) | USD | $50 |
| OPay | [#4](https://github.com/zkp2p/peer-link/issues/4) | NGN | $50 |
| Easypaisa | [#86](https://github.com/zkp2p/peer-link/issues/86) | PKR | $50 |
| BCA | [#7](https://github.com/zkp2p/peer-link/issues/7) | IDR | $50 |
| Bancolombia | [#9](https://github.com/zkp2p/peer-link/issues/9) | COP | $50 |
| GCash | [#10](https://github.com/zkp2p/peer-link/issues/10) | PHP | $50 |
| bKash | [#13](https://github.com/zkp2p/peer-link/issues/13) | BDT | $50 |
| Safaricom M-Pesa | [#14](https://github.com/zkp2p/peer-link/issues/14) | KES | $50 |
| Kaspi Bank | [#15](https://github.com/zkp2p/peer-link/issues/15) | KZT | $50 |
| BBVA Mexico | [#16](https://github.com/zkp2p/peer-link/issues/16) | MXN | $50 |
| Banco de Credito del Peru | [#17](https://github.com/zkp2p/peer-link/issues/17) | PEN | $50 |
| Ziraat Bank | [#18](https://github.com/zkp2p/peer-link/issues/18) | TRY | $50 |
| Uala Argentina | [#20](https://github.com/zkp2p/peer-link/issues/20) | ARS | $50 |
| Itau Brazil | [#21](https://github.com/zkp2p/peer-link/issues/21) | BRL | $50 |
| MTN MoMo Ghana | [#32](https://github.com/zkp2p/peer-link/issues/32) | GHS | $50 |
| BBVA Spain | [#24](https://github.com/zkp2p/peer-link/issues/24) | EUR | $50 |

The list balances Peer's US demand with large P2P markets across Latin America,
Africa, Asia and Europe, and only uses banks whose issues and logos already
exist in this repository. See [integration priorities](integration-priorities.md).
`app/bounties.json` mirrors this table for the website; keep both in sync with
the GitHub `Merit` + `$50` labels, which Merit uses to list bounties.

History: the earlier unfunded $10,000 / 60-bank proposal ($150–$200 per bank)
was retired on October 2, 2026 with no claims or payouts. The interim $25 US
feasibility scopes were upgraded the same day to full $50 adapter awards.

## How to claim

1. Comment on the bank's issue with the surface (app or web page) and transfer
   type you will cover, and confirm you or a collaborator are authorized to use
   an account there. Never post credentials, real records or identity documents.
2. A maintainer assigns one attempt for 14 days, extendable in writing.
   Unassigned competing work creates no additional payment obligation.
3. Build with your agent using [the contribution skill](../skills/contribute-bank/SKILL.md).
   Open a PR that says `Closes #<issue>`. Submissions are due
   **2026-11-15 23:59 UTC**.

## Acceptance

- Original, MIT-compatible, pure and deterministic adapter with a manifest and
  acquisition notes. No network, credentials, filesystem access or payment
  initiation in adapter code. Do not copy private Peer or third-party code.
- Synthetic fixtures with independently justified expected outputs and
  meaningful negative tests (wrong payer/payee, amount/currency mismatch,
  nonfinal/unknown status, missing identifiers, malformed input, duplicate
  selection, untrusted memo text). Ambiguity fails closed.
- `npm run check` and `npm run privacy -- --staged` pass before every push.
- One privacy-safe live report from the authorized account owner, bound to the
  exact adapter and harness commits, using an existing transaction. Synthetic
  tests alone are not a live report. **There is no three-user testing requirement.**

## Payment

Maintainer @0xSachinK reviews against the written scope, records acceptance on
the issue and pays through Merit. Merge, coverage, AI output and enclave reports
never trigger payment by themselves, and bounty acceptance is separate from Peer
production support. One award per bank, $50 total including any collaborator
split agreed before starting. Disputes are judged against the written scope;
disclose conflicts of interest.

Contributors complete wallet, tax and payout-eligibility setup directly with
Merit and should confirm that payouts are available in their country before
starting. Never submit identity or banking documents in GitHub.

Mercury is the internal baseline adapter; existing founder work does not earn a
bounty. Integrations for any other bank are welcome without a reward promise —
open a [bank request](https://github.com/zkp2p/peer-link/issues/new?template=bank-request.md).
