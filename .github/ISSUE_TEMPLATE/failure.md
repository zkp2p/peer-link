---
name: Transcript contribution failure
about: Report a structural or fixed-code failure without sharing banking data
labels: bug
---
<!-- Raw bank responses, API keys, sessions, screenshots, account/transaction identifiers,
request headers and unredacted model text must never appear here.
Report security/privacy exposures privately through SECURITY.md. -->

Bank campaign issue:
Public release/source revision:
Step that failed (availability / attestation / reservation / acquisition / grading / receipt / payout):
Fixed reason code:
Expected and observed behavior (no private values):
Synthetic structural reproducer (optional; invented data only):
Limitations:

Do not retry an uncertain payout by starting another job: keep polling the saved
state file as the contribution skill describes. A listed campaign does not
establish that a bank has been acquired successfully before.
