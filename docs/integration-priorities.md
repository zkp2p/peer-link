# Integration priorities — October 2, 2026

The funded program covers 20 banks at $50 each from the $1,000 Merit project pool; each
bank issue states its narrow scope, folder and deadline, and
[issue #64](https://github.com/zkp2p/peer-link/issues/64) and [incentives](incentives.md)
hold the program terms. Chase, Bank of America and Wells Fargo were upgraded from $25
feasibility scopes to full $50 adapter awards. This page is an execution guide for
assigning and reviewing that work, not a revenue forecast: no bank-specific Peer usage or
conversion data was available, and earlier P2P liquidity snapshots measured standing book
depth and ad activity, not settled volume.

## What makes an assignment likely to succeed

1. **An authorized account owner who has said so in the issue.** Implementation skill
   without account access cannot produce the required live report.
2. **A browser-reachable structured response.** The contributor workflow inspects the JSON
   a web page or documented personal API returns. Mobile-only apps, USSD and SMS
   confirmations need an agreed input format before work starts, and an SMS text is not
   authenticated by itself.
3. **An exact counterparty identifier and an explicit final status.** Interbank references
   named in the issues (Pix end-to-end ID, SPEI tracking key, SEPA IBAN, CCI, CVU, NIP
   session ID) make "A paid B" checkable; masked numbers and display names do not.
4. **Documented precision.** Several currencies (VND, COP, KZT, IDR) are often shown
   without minor units; the adapter must record what the bank reports and the
   `currencyExponent` it emits.

## Funded banks

Access signals are as of October 2, 2026; "none yet" means no comment on the issue.

| Bank | Issue scope (one type, pick and document) | Access signal | Main semantic risk |
| --- | --- | --- | --- |
| [Monobank](https://github.com/zkp2p/peer-link/issues/6) | UAH IBAN/account or card-to-card transfer | Implementation lead without an account; owner still needed | Masked card suffixes; personal API token must stay local |
| [Vietcombank](https://github.com/zkp2p/peer-link/issues/8) | VND domestic transfer (incl. NAPAS 24/7) on Digibank | Contributor lead waiting on funding; must reconfirm and check Merit payout in Vietnam | VND precision; exact recipient on history vs detail view |
| [Chase](https://github.com/zkp2p/peer-link/issues/73) | USD Zelle or ACH | None yet | Zelle, ACH and wire semantics differ; `sent` is not credit |
| [Bank of America](https://github.com/zkp2p/peer-link/issues/74) | USD Zelle or ACH | None yet | Pending and scheduled items must abstain |
| [Wells Fargo](https://github.com/zkp2p/peer-link/issues/75) | USD Zelle or ACH | None yet | Same as above |
| [Itaú](https://github.com/zkp2p/peer-link/issues/21) | BRL Pix with end-to-end ID | None yet | Pix keys and CPF numbers must never enter fixtures |
| [BBVA Mexico](https://github.com/zkp2p/peer-link/issues/16) | MXN SPEI with tracking key | None yet | CEP lookup is a separate Banxico surface |
| [BBVA Spain](https://github.com/zkp2p/peer-link/issues/24) | EUR SEPA standard or instant | None yet | Bizum is out of scope; masked IBANs |
| [BCP](https://github.com/zkp2p/peer-link/issues/17) | PEN BCP-to-BCP or interbank CCI | None yet | Yape is a separate surface |
| [Ziraat Bank](https://github.com/zkp2p/peer-link/issues/18) | TRY havale/EFT or FAST | None yet | Masked IBANs and names are not identifiers |
| [Bancolombia](https://github.com/zkp2p/peer-link/issues/9) | COP internal or Bre-B/Transfiya | None yet | COP precision as reported |
| [BCA](https://github.com/zkp2p/peer-link/issues/7) | IDR BCA-to-BCA or BI-FAST | None yet | Mutation lists may omit the counterparty |
| [Kaspi Bank](https://github.com/zkp2p/peer-link/issues/15) | KZT Kaspi-to-Kaspi by phone or card | None yet | Partial recipient names as the only identifier |
| [Ualá](https://github.com/zkp2p/peer-link/issues/20) | ARS transfer by CVU/alias | None yet | COELSA reference may be absent |
| [OPay](https://github.com/zkp2p/peer-link/issues/4) | NGN OPay-to-OPay or OPay-to-bank | None yet | Wallet vs NIP transfers; session IDs |
| [Easypaisa](https://github.com/zkp2p/peer-link/issues/5) | PKR wallet transfer or IBFT/Raast | None yet | Masked mobile numbers |
| [GCash](https://github.com/zkp2p/peer-link/issues/10) | PHP Send Money or InstaPay | None yet | Masked mobile numbers; reference numbers |
| [bKash](https://github.com/zkp2p/peer-link/issues/13) | BDT Send Money | None yet | Cash Out, Payment and Recharge excluded |
| [Safaricom M-Pesa](https://github.com/zkp2p/peer-link/issues/14) | KES Send Money | None yet | SMS provenance; Lipa na M-Pesa and Fuliza excluded |
| [MTN MoMo Ghana](https://github.com/zkp2p/peer-link/issues/32) | GHS MoMo-to-MoMo | None yet | SMS provenance; merchant payments excluded |

## Assignment and review guidance

- Assign in the order owners confirm authorized access, not in table order. Confirm the
  surface and input format in the issue before the 14-day attempt starts, especially for
  mobile-money services.
- One award per bank, including any collaborator split agreed before starting. Pair an
  implementation lead with a consenting account owner rather than accepting a parser
  without a live report.
- Review against the issue's written scope. A finding that the surface cannot establish
  exact payer, payee and completed status is valuable, but a limitation-only result needs a
  revised scope agreed in the issue before it can be accepted for payment.
- Mercury remains the internal baseline adapter; existing founder work does not earn a
  bounty. Existing private implementations are not public contributions and do not
  establish product enablement; do not commission a copy of private code.
- Other banks stay welcome as unpaid contributions through the bank-request template.

## Primary sources, checked October 2, 2026

- [Monobank personal API](https://api.monobank.ua/docs/index.html): personal account and
  token scope, statement fields and rate limits; the service-provider API is a separate path.
- [Vietcombank transaction-history guide](https://digibankm5.vietcombank.com.vn/get_file/ibomni/html/hdsd-ib/pages/vi/tinh-nang-giao-dich-ngan-hang/tai-khoan/3-lich-su-giao-dich.html):
  history access, not an assurance of exact recipient semantics.
- [Mercury API getting started](https://docs.mercury.com/docs/getting-started): read-only
  tokens exist; a separately reviewed read-only API surface is preferable to a powerful
  browser session when it establishes the necessary fields, but it is not interchangeable
  with the existing web adapter.
- [Federal Reserve large-bank data](https://www.federalreserve.gov/releases/lbr/): footprint
  proxy only, not Peer usage or transfer demand.
- Bank issues linked above, read October 2, 2026: scopes, folders and existing comments.
  Comments are leads, not evidence of an earned payout or a verified adapter.
