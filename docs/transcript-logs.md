# Transcript service logs

The transcript service sends payload-free operational logs to Axiom for debugging
and monitoring. Nothing a contributor submits is logged: the relay outside the
enclave only ever holds ciphertext, and it logs fixed public facts about each
request.

## Path

```
host units ──journal──▶ log shipper ──instance role──▶ CloudWatch Logs group
                                                         │ subscription
                                                         ▼
                                              forwarder Lambda ──▶ Axiom dataset
```

| Piece | Where | Notes |
| --- | --- | --- |
| Relay events | `transcripts/server.py` on the host | One JSON line per request and per egress connection. Outside the measured image. |
| Log shipper | `transcripts/infra/log_shipper.py`, unit `peer-link-transcript-logs` | Follows the journal of the transcript units, forwards a fixed set of fields, masks network addresses in free text. Uses the instance role; holds no Axiom token. |
| Log group | `/peerlink/transcripts/host`, stack `peerlink-transcript-logs` | 30 days retention. The host role may only create a stream and put events there. |
| Forwarder | Lambda in the same stack, `transcripts/infra/axiom_forwarder.py` | Holds an ingest-only Axiom token scoped to one dataset. |
| Dataset | `peerlink-transcripts-prod` in the Peer Axiom organisation | Query with `axiom query` or the Axiom UI. |

The enclave itself does not log. What happens to a job inside it is visible from
the outside as the public job status the relay passes back, which is what the
`state` and `reason` fields below record.

## What is logged

`request` events, one per HTTP request to the relay:

| Field | Meaning |
| --- | --- |
| `command` | `health`, `campaigns`, `attest`, `reserve`, `challenge`, `submit`, `status`, `receipt`, `operator`, or `unrouted` |
| `status`, `ms`, `requestBytes`, `responseBytes` | HTTP status, time and sizes |
| `jobId`, `campaignId` | The public random job id and the campaign |
| `provider`, `model` | On `reserve` only: the named provider and model id the contributor chose |
| `state`, `reportedState`, `reason`, `error` | The public job state and fixed reason or error code |
| `transactionId` | The Base payout transaction once a job is paid |
| `action` | On `operator` only: `pause`, `resume`, `activate`, `reconcile`, `retire` or `preflight` |

An `unrouted` request never reached the enclave: it is answered 404 `route_not_found`,
or 400 with a framing code such as `input_size` or `invalid_json`. Status 503 with
`service_unavailable` on a routed command means the enclave did not answer.

`egress` events, one per outbound connection the enclave opens through the relay:
`target`, `outcome` (`closed`, `idle`, `denied`, `unavailable`, `limit`, `error`),
`ms` and `bytes`. `target` is a fixed service host, a named model provider, or the
campaign's bank domain; a contributor's own model endpoint is logged as `other`.

`health` events, one a minute from the health publisher's localhost probe on a
continuous host: `RuntimeHealth` and `AdmissionsOpen`, each `0` or `1`, the same
values it sends to CloudWatch. `RuntimeHealth` is `0` when the relay or enclave
does not answer or its answer fails the policy-bound check; `AdmissionsOpen` is `0`
while paused, including after every restore until a signed resume. A single `0`
can be a probe that exceeded its 5 second timeout; like the CloudWatch alarm, treat
three consecutive `0` samples as an outage. No sample for several minutes means the
host, the publisher or the log path is down.

Lifecycle lines from the other units (`enclave`, `credentials`, `health`,
`archive-sync`) are forwarded as text with network addresses and long opaque runs
masked. On the enclave unit, `status=1/FAILURE` means the supervisor's startup or
liveness check failed; an operator stop or restart ends with `Deactivated
successfully`.

Never logged: request or response bodies, ciphertext, signatures, bank sessions,
inference keys, raw or redacted transcripts, notes, payout addresses, client IP
addresses, custom inference base URLs, and bank hosts below the campaign domain.
`transcripts/tests/test_logs.py` holds these as tests.

## Useful queries

```
axiom query "['peerlink-transcripts-prod'] | where event == 'request' and command == 'status' and state == 'rejected' | summarize count() by reason, campaignId"
axiom query "['peerlink-transcripts-prod'] | where event == 'request' and command == 'reserve' | project _time, campaignId, provider, model, state, error"
axiom query "['peerlink-transcripts-prod'] | where event == 'egress' and outcome != 'closed' | summarize count() by target, outcome"
axiom query "['peerlink-transcripts-prod'] | where unit != 'relay' | project _time, unit, message"
axiom query "['peerlink-transcripts-prod'] | where event == 'health' | summarize samples = count(), unhealthy = countif(RuntimeHealth == 0), paused = countif(AdmissionsOpen == 0) by bin(_time, 1h)"
```

## Install or update

1. Create the dataset and an ingest-only API token scoped to it in Axiom. Use a
   dedicated token, never a personal one.
2. Create or update the stack from `transcripts/infra/logs.cfn.json`, passing
   the token as the `AxiomToken` parameter from a file that is deleted
   afterwards. The parameter is `NoEcho`; do not put the token in a shell
   command, an SSM command or a log.
3. Append `logs_template.host_statements(<group arn>)` to the host role policy
   and add `logs:CreateLogStream` and `logs:PutLogEvents` to its catch-all
   `NotAction` list, with an additive change set as for the archive mirror.
4. On the host, through SSM, run `transcripts/infra/install_log_shipper.sh` with
   the script's SHA-256, the log group, the region and the instance id. It does
   not touch the relay, enclave, credential or health units.
5. Relay events need the host's `transcripts/server.py` at a revision that emits
   them, and the relay unit's `StandardOutput=journal` (`install_release.sh`
   sets it; a host installed earlier needs a drop-in with that one line). Its
   `StandardError` stays `null`. The enclave unit requires the relay unit, so
   replacing the relay file or its unit restarts the enclave: pause first,
   replace and restart, verify with the client's `preflight`, then send a
   signed `resume`.
6. Health events need the host's `transcripts/infra/health_publisher.py` at a
   revision that prints them and the health unit's `StandardOutput=journal`
   (`install_continuous.sh` sets it; a host installed earlier needs a drop-in with
   that one line). Restarting the health unit alone leaves the relay and enclave
   running.

The host role cannot read, filter or delete log events, and the Axiom token
never reaches the host. A compromised host could add false lines to the group;
it could not read what is already there or reach any other dataset.
