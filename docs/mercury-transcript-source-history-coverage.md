# Mercury Transcript Source and History Coverage

> This issue is retained as a Mercury evidence/coverage discussion during the transcript-program migration.

## Status

* Provider-code bounty workflow for Mercury is retired.
* No public submission slot is currently open for Mercury.
* New contributions use the transcript skill after an approved release and explicit campaign reservation.
* The eventual bank campaign will publish its $5/$10 rate and 1–5-contributor capacity. This historical technical issue does not create a separate payable slot.

Prior earned or accepted commitments remain governed by their original terms.

## Scope of discussion

Discuss public schema and endpoint patterns only. Never post banking credentials, account identifiers or raw records.

## Public Schema

Public transcript metadata for Mercury source coverage:

```json
{
  "transcript_id": "string",
  "source": "mercury",
  "source_version": "string",
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "history": [
    {
      "event_id": "string",
      "event_type": "string",
      "timestamp": "ISO-8601",
      "actor": "public_identifier",
      "operation": "string",
      "evidence_ref": "string"
    }
  ],
  "coverage": {
    "source_coverage": "boolean",
    "history_coverage": "boolean",
    "last_verified_at": "ISO-8601"
  }
}
```

Notes:
* `actor` must be a public identifier, never a banking credential or account number.
* `evidence_ref` is an opaque reference to public evidence, not raw records.

## Endpoint Patterns

Public read-only patterns for transcript source and history:

* `GET /transcripts/{transcript_id}`
  Returns public metadata and coverage flags. No sensitive fields.

* `GET /transcripts/{transcript_id}/history`
  Returns paginated history events with `event_id`, `event_type`, `timestamp`, `operation`, `evidence_ref`.

* `GET /sources/mercury/coverage`
  Returns aggregate public coverage summary for Mercury source. No per-account data.

All endpoints must enforce public schema filtering and redact any banking credentials, account identifiers or raw records.

## Contribution guidance

New contributions use `skills/contribute-transcript/SKILL.md` after an approved release and explicit campaign reservation. Do not open Mercury provider-code submissions outside the transcript program.
