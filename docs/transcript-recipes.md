# Writing a transcript recipe

This guide is for the local agent preparing an `open_recipe` contribution. It
explains what Peer engineers need from a bank, how to find the request that
provides it, and how to describe it so the contribution is accepted. The step
order and commands are in the
[contribution skill](../skills/contribute-transcript/SKILL.md).

## What an integration needs

A Peer bank integration fetches one payment from the bank inside an enclave and
reduces it to five bank-derived values: a payment id, the payee, the amount, the
currency and a timestamp. It also checks a status. The existing integrations
for wallets, neobanks and US bank Zelle flows all follow that shape, and they
differ in exactly the details a transcript can record:

| Value | What engineers have to learn about the bank |
| --- | --- |
| Payment id | Which field is unique per payment and stable across reads. |
| Payee | Which field identifies the other party in a form a seller could register and a buyer could pay to: an account or user id, a handle or username, an email or phone alias. A display name alone is weak because it is not unique. |
| Amount | The unit and sign convention. Shipped integrations have met integer minor units, minor units sent as strings, decimal numbers in major units, negative values for money sent, and display text with a sign and currency symbol. |
| Currency | Whether a code accompanies the amount or the rail implies it. |
| Timestamp | The format (ISO string, epoch seconds or milliseconds) and which of several times means the payment is done: created, completed, settled or posted. |
| Status | The tokens that mean completed, and any type or scheme field that separates a person-to-person transfer from a card payment or a request. |
| The request | Method, host, path, query, the smallest set of session headers that works, and the body for a POST or GraphQL call. |

A good contribution therefore shows the list of recent payments with those
fields, on the request the bank's own site uses, with as few headers as
possible.

## Find the request

1. If the bank publishes an API with a personal read-only token, use it. A token
   is simpler than a browser session and can be revoked on its own.
2. Otherwise have the owner sign in, open the browser's developer tools on the
   Network tab, filter to Fetch/XHR, and open the activity or transactions page.
   The request you want returns JSON containing the rows shown on screen. Prefer
   the list the page itself loads over an export or statement download.
3. If clicking one payment loads a detail response keyed by its id, add that
   request as an extra read after the list. Engineers often build on the detail
   call because it carries the payee identifier the list omits.
4. Note the host. Many banks serve the page from one host and the JSON from
   another under the same domain; every read in one recipe must use a single
   `https://host`, and that host must be the campaign domain or a subdomain.
5. Size the page so at least three records come back, using the site's own
   `limit`, `count` or page-size parameter. Twenty is plenty; responses over 2 MB
   are refused.

Only replay requests the site issues while the owner is viewing history. Do not
replay anything issued by a send, confirm, edit, settings or logout action.

A cloud-backed agent that reads the Network tab or a pasted request sees the
session headers and the response. Tell the owner before you look, and prefer
having the owner export the secrets as environment variables.

## Reduce the session headers

Start from the request headers the browser sent, then remove one at a time and
rerun `preview` until the read fails, keeping only what is required. Sets that
real integrations have needed:

- a single authorization token for public APIs;
- the session cookie plus a CSRF header whose value is tied to that session;
- the cookie plus device or channel headers the web app adds to every call;
- `Origin` and `Referer` on sites that check them.

Do not include `Host`, `Content-Length`, `Connection`, `Transfer-Encoding` or
`Accept-Encoding`; the enclave sets or refuses those. Do not include
`Content-Type` for a POST; it comes from the read's `contentType`. Header names
and values must be printable ASCII, with at most 24 headers.

For `credential.kind: "headers"` the secret is one JSON object of header name to
value. With `--secrets-from-env` that object is the content of
`PEERLINK_BANK_CREDENTIAL`:

```json
{
  "X-Device-Id": "<device id value from the request>",
  "Referer": "https://app.examplebank.com/activity"
}
```

The session cookie and any CSRF header go in the same object under their own
header names, each with the full value the browser sent. Only the header names
are kept in the transcript.

## Write the reads and selectors

```json
{
  "version": 3,
  "reads": [
    {"url": "https://app.examplebank.com/api/v2/me"},
    {"url": "https://app.examplebank.com/api/v2/activity?limit=20"}
  ],
  "identity": {"read": 0, "path": ["user", "id"]},
  "history": {"read": 1, "path": ["activity", "items"]}
}
```

- A read is `{"url": ...}` for GET. URLs use `https`, no port, no fragment and no
  percent-encoding in the path, and each query name appears once.
- `identity` points at one stable account, user or organization id in an
  authenticated response: a number of at least 100, or a string of 3 to 200
  characters without spaces. Take it from a profile, session or accounts read,
  or from a top-level field of the history response. Do not use a transaction
  field, a name or a balance. It decides whether the same account was already
  paid in the campaign, and its value is never kept.
- `history` points at the array of transaction records. It needs at least three
  object records.
- A path is a list of object keys and array indexes read left to right. `[]`
  selects the whole response, `[0, "id"]` selects `id` of the first element.
- The identity and history requests must fail or return something other than
  JSON when sent without the session. The enclave checks this first, because a
  public endpoint proves nothing about an account.

A POST read replays the body the site sent, as one line:

```json
{
  "url": "https://app.examplebank.com/api/graphql",
  "method": "POST",
  "contentType": "application/json",
  "body": "{\"operationName\":\"GetActivityQuery\",\"variables\":{\"first\":20},\"query\":\"query GetActivityQuery($first: Int) { activity(first: $first) { items { id amount } } }\"}"
}
```

`contentType` is `application/json` or `application/x-www-form-urlencoded`, and
`body` is at most 16384 printable ASCII characters with no line breaks. The
enclave refuses a POST whose path contains a segment such as `transfer`, `send`,
`pay`, `create`, `update`, `delete`, `cancel`, `submit` or `confirm`, whose
GraphQL document is a `mutation`, or whose `operationName` contains `mutation`
or begins with a write verb such as `create`, `update`, `delete`, `send`, `set`
or `add`. A read-only operation whose name happens to begin that way is refused
too; report it on the bank's campaign issue. The transcript keeps the body's
field names and format classes and the GraphQL operation name, not the document
text.

## Read the preview

`preview` prints the transcript the enclave would keep. Each request lists its
response fields by path, where `[]` marks array elements and `{key}` replaces an
object key that looks like an identifier:

```json
{
  "step": 2,
  "method": "GET",
  "origin": "https://app.examplebank.com",
  "path": "/api/v2/users/{id}/activity",
  "query": [{"name": "limit", "value": "20"}, {"name": "cursor", "value": "{digits:10}"}],
  "status": 200,
  "fields": {
    "$.activity.items[].amount": {"types": ["string"], "formats": ["decimal:neg:2", "decimal:pos:2"]},
    "$.activity.items[].createdAt": {"types": ["string"], "formats": ["datetime:iso8601:utc"]},
    "$.activity.items[].status": {"types": ["string"], "formats": ["text:medium:alpha", "text:short:alpha"], "values": ["completed", "pending"]}
  }
}
```

| Format class | Meaning |
| --- | --- |
| `int:pos:N`, `int:neg:N`, `int:zero:1` | Integer with N digits. |
| `int:epoch_s`, `int:epoch_ms`, `digits:epoch_s`, `digits:epoch_ms` | Epoch time, reported only under a time-like key such as `createdAt`. |
| `float:pos:N`, `float:neg:N` | JSON number with N fraction digits. |
| `decimal:pos:N`, `decimal:neg:N` | Numeric string with N fraction digits. |
| `digits:N`, `digits:neg:N` | String of N digits, optionally negative. |
| `datetime:iso8601:utc`, `:offset`, `:naive` | ISO date-time ending in `Z`, with an offset, or with no zone. |
| `date:iso8601`, `date:slash` | `2026-10-01` or `10/01/2026` style date. |
| `currency_code`, `money_text` | ISO 4217 code; display text containing digits and a currency symbol or code. |
| `uuid`, `email`, `url`, `hex:short`, `hex:long`, `empty` | Recognised shapes. |
| `text:<size>:<charset>` | Other text: `short` up to 8 characters, `medium` up to 32, `long` up to 128, else `xlong`; `alpha`, `alnum` or `mixed`. |

`values` appears only under keys ending in `status`, `state`, `type`, `kind`,
`currency`, `scheme`, `direction`, `method`, `rail` or `network`, for short
tokens, and never under an object that describes a person or address.
`valuesIncomplete` means a token was withheld because the same text also
occurred as an ordinary value. Path segments and query values that are not plain
words become `{id}` or a format class. If anything personal still shows, change
the reads or stop; do not contribute it.

## Map the roles

Pick each role from `historyFieldPaths` and check it with
`preview --mapping`. A role path starts at a record and descends through object
keys only, so `$.items[].amount.value` works and `$.items[].legs[].amount` does
not. Each path can serve one role.

| Role | Weight | Required | Verified when |
| --- | --- | --- | --- |
| `paymentId` | 25 | yes | Present on at least 90% of records and different on every record. |
| `amount` | 25 | yes | A number, numeric string or money text on at least 90% of records. |
| `timestamp` | 20 | yes | An ISO date or date-time, a slash date, or epoch seconds or milliseconds on at least 90% of records. |
| `counterparty` | 15 | yes | A non-empty string or integer on at least half of the records. |
| `status` | 10 | no | A short token on at least 90% of records with at most 12 distinct values. |
| `currency` | 5 | no | An ISO 4217 code on at least 90% of records. |

The minimum score is 85, which is exactly the four required roles.

## Pitfalls seen in real integrations

| Symptom | Cause and fix |
| --- | --- |
| `preview` works, the job fails with `bank_http_unauthorized` or `bank_http_redirect` | Sessions on bank web apps can expire within minutes and CSRF values die with them. Capture fresh headers, run `preview` once, and contribute immediately. Some banks also refuse data-centre addresses; that cannot be fixed from a recipe. |
| `bank_response_non_json` | The URL returned an HTML page, often a login page served with status 200. Use the JSON endpoint the page calls. |
| `response_encoding` | The server compressed the body although the enclave asks for `Accept-Encoding: identity`. Try the API host rather than the page host. |
| `history_path_invalid` | The list is wrapped, for example under `data`, `transactions` or `activity.items`. Point `history` at the array itself. |
| `insufficient_history` | Fewer than three object records. Raise the page size or widen the date filter. |
| `mapping_missing_counterparty` | Only person-to-person rows carry a counterparty. Use the transfers or payments list rather than the full card-and-fee ledger, or map a field that exists on most rows. |
| `mapping_missing_timestamp` | The field is a compact date such as `20261001` or localized text, which is not recognised. Map another time field if the record has one, otherwise report it on the campaign issue. |
| `mapping_missing_paymentId` | The mapped field repeats across rows, such as an account id or a batch id. |
| Amount looks wrong to engineers | State the convention in the notes: minor or major units, and whether negative means sent. |
| `write_request_refused` | The path or operation name reads like a state change. Choose the request that lists history. |

## Write notes that make the mapping succeed

The notes are placed in the model prompt between PeerLink's instructions and the
transcript, and they are kept with an accepted transcript. Write them for an
engineer who will build the integration:

- One sentence per role naming the exact path `preview` printed, for example
  "amount is $.activity.items[].amount".
- The unit and sign of the amount, which time field means the payment is done,
  and which status token means completed.
- How the payee field relates to what a sender types: handle, email, phone or
  account id.
- Anything about the request an engineer could not see from the transcript:
  which page loads it, how pagination works, how long the session lasts.

Notes are limited to 4000 characters and are rejected with `unsafe_notes` when
they contain an email address, six or more digits in a row, a run of 28 or more
letters, digits, hyphens and underscores, the word `bearer` followed by another
word, the identity value, or any response value of six or more characters that
contains a digit or `@`. Status tokens and currency codes are fine to name;
describe everything else instead of quoting it.

## Worked example: a public API with a token

Wise publishes a personal API whose read-only token works well as an
illustration. Wise is already integrated in Peer and has no public reward, so
use this as a pattern rather than a campaign. The ids below are invented.

`.local/payload.json`:

```json
{
  "credential": {"origin": "https://api.wise.com", "kind": "bearer"},
  "profileId": null,
  "recipe": {
    "version": 3,
    "reads": [
      {"url": "https://api.wise.com/v1/profiles"},
      {"url": "https://api.wise.com/v1/transfers?profile=10000001&limit=20"}
    ],
    "identity": {"read": 0, "path": [0, "id"]},
    "history": {"read": 1, "path": []}
  },
  "notes": "Public API with a personal read-only token. The transfers list is newest first. paymentId is $[].id. amount is $[].targetValue, a positive number in major units of $[].targetCurrency. timestamp is $[].created, a UTC time written without a zone. counterparty is $[].targetAccount, the recipient account id. status is $[].status and outgoing_payment_sent means completed.",
  "transcript": []
}
```

The first read returns an array of profiles, so `[0, "id"]` is the first
profile's id. The second read returns a bare array of transfers, so the history
path is `[]` and every role path starts with `$[]`.

`.local/mapping.json`:

```json
{
  "paymentId": "$[].id",
  "amount": "$[].targetValue",
  "timestamp": "$[].created",
  "counterparty": "$[].targetAccount",
  "currency": "$[].targetCurrency",
  "status": "$[].status"
}
```

With the token in `PEERLINK_BANK_CREDENTIAL` and any non-empty value in
`PEERLINK_INFERENCE_KEY`:

```sh
.local/transcript-venv/bin/python -m transcripts.cli preview \
  --campaign <campaign-id> --secrets-from-env --mapping .local/mapping.json \
  < .local/payload.json
```

The transcript shows the second request as `/v1/transfers` with query
`profile={digits:8}` and `limit=20`, fields such as `$[].created` with format
`datetime:iso8601:naive` and `$[].status` with its tokens, and an assessment of
100 with all six roles verified.

## Worked example: a web session with a POST

An invented bank whose activity page posts a JSON filter. The owner exports the
header object described above.

```json
{
  "credential": {"origin": "https://secure.examplebank.com", "kind": "headers"},
  "profileId": null,
  "recipe": {
    "version": 3,
    "reads": [
      {"url": "https://secure.examplebank.com/api/profile/summary"},
      {
        "url": "https://secure.examplebank.com/api/payments/activity/list",
        "method": "POST",
        "contentType": "application/json",
        "body": "{\"pageSize\":25,\"sortBy\":\"DATE\",\"order\":\"DESC\"}"
      }
    ],
    "identity": {"read": 0, "path": ["profile", "customerId"]},
    "history": {"read": 1, "path": ["listItems"]}
  },
  "notes": "The activity page posts this filter when it opens. paymentId is $.listItems[].id. amount is $.listItems[].amount, a decimal string in major units, always positive. timestamp is $.listItems[].completedAt. counterparty is $.listItems[].recipient.alias, the email or phone the sender typed. status is $.listItems[].status and COMPLETED means done.",
  "transcript": []
}
```

POST reads are accepted only when the campaign's `methods` include `POST`. The
transcript records this request as `POST /api/payments/activity/list` with a
body shape of `pageSize`, `sortBy` and `order` and their format classes.
