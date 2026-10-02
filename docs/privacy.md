# Privacy before publication

Public PRs, comments and Git history are persistent. Deleting a file later does not undo a
leak: every pushed commit stays retrievable.

## Agent workflow

- Before inspecting a bank, identify the minimum fields the capability requires. Tell the
  account owner when their chosen cloud agent processes banking data; repository
  instructions do not authorize sharing data with unrelated services.
- Do not export whole HARs, cookie jars, browser profiles, account statements or agent
  transcripts. Raw local files belong only in the Git-ignored `.local/` folder, with
  restricted permissions and a deliberate cleanup plan.
- Prefer learning a response's structure without its values:
  `npm run try:bank -- --shape .local/<file>.json` prints keys and value descriptions and
  keeps only enum-like status, type, direction and currency values. `npm run try:bank` and
  the in-page harness print redacted summaries with masked identifiers.
- Prefer independently invented synthetic fixtures. For sanitized observations, replace
  names, account/routing IDs, transaction and organization IDs, dates, amounts, addresses,
  emails, references and free-text memos. Remove unrelated transactions, headers and
  metadata entirely. Preserve relevant sign, precision, duplicate/matching relationships
  and status behavior. Do not hash real low-entropy account identifiers as a substitute for
  redaction.
- Mark fixture provenance `synthetic` or `sanitized` (also in the file name); explain
  transformations and limitations. Never call sanitized bytes authenticated original
  evidence.
- Review expected outputs too. They can contain the same sensitive values as inputs.
- Publish only minimum code, fixtures and structured reports. No original bank
  screenshots, statements or transcript attachments.

## Invented values that pass the checks

| Kind | Use |
| --- | --- |
| Names | Contain a marker: `Synthetic Payee`, `Example Account Holder`. |
| Emails | Reserved domains: `payer@example.com`, `payee@bank.example`, `a@mail.test`. |
| Account numbers | Runs of zeros: `000000000001`, `0000000000000000001`. |
| IBANs | A published registry example (`GB82WEST12345698765432`, `UA213223130000026007233566001`) or check digits `00`. |
| Card numbers | Network test numbers (`4111111111111111`) or a number that fails the Luhn check. |
| Phone numbers | Obviously fictional with `0000`: `+380670000001`. |
| Transaction IDs | `synthetic-transfer-001`, or a UUID you generated. |
| Dates and amounts | Invented values that keep the original precision, sign and timezone format. |

## Required commands before publishing

```sh
npm run privacy -- --staged                    # exact index contents before each commit
npm run privacy -- --range origin/main..HEAD   # every file version in your branch history
git diff origin/main...HEAD                    # read every line you are about to push
```

The scanner never prints matching values. It flags private keys, tokens, API keys, cookies,
authorization and CSRF headers (JSON, HAR and raw HTTP forms), JWTs, session cookie values,
raw capture and statement file types, and media or documents under `banks/`. In bank
folders it also flags non-reserved email addresses, checksum-valid IBANs and card numbers,
US social security numbers and credential-bearing URLs; in fixtures, real-looking phone
numbers, person names without a synthetic marker and missing provenance, and it warns about
unexplained long numeric identifiers. Heuristics do not certify privacy: names, amounts and
uncommon identifiers can evade them. CI runs the same checks too late to prevent the first
disclosure, so run them locally.

## Accidental exposure

Stop sharing, revoke exposed credentials through the account owner, contact the maintainer
privately (see [SECURITY.md](../SECURITY.md)) and follow GitHub's sensitive-data removal
procedure. Never repeat the secret in an issue or PR comment.

The landing page accepts no bank uploads and runs only a synthetic example. Hosting
providers can receive ordinary access metadata; no analytics or tracking SDK is included.
