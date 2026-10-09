# Transcript archive (S3)

Every signed, redacted record the enclave releases to the operator host is mirrored
to a private S3 bucket. Peer engineers read accepted transcripts from there when
writing Curator metadata and attestation transformers.

The mirror is host-side tooling. It is **not** part of the measured enclave image,
changes no PCR, and adds no trust: it copies bytes the enclave already validated,
signed and handed to the host. It never sees bank sessions, inference keys or raw
bank responses, because those never leave the enclave.

## Where records live

| | |
| --- | --- |
| Bucket | `peerlink-transcripts-411399509833` (us-east-1) |
| Stack | `peerlink-transcript-archive`, from `transcripts/infra/archive.cfn.json` |
| Access | Private. All four public-access blocks on, bucket-owner-enforced, TLS-only bucket policy |
| Durability | Versioning on, SSE-S3 (AES256), `Retain` on stack deletion, no lifecycle expiry |

Two keys per record, identical bytes:

```text
records/<sha256>.json
by-bank/<bankId>/<campaignId>/<jobId>/<state>-<sha256 first 12>.json
```

`records/` is content-addressed: the object name is the SHA-256 of its bytes, the
same name the host archive uses. `by-bank/` is the browsable copy. A job normally
has one record per settlement state it passed through (`accepted`, `payout_pending`,
`paid`); the `paid` record carries the payout transaction ID. `bankId` contains a
slash, for example `us/mercury`.

Each object is the canonical JSON `{"payload": {...}, "signature": "..."}` written
by `transcripts/storage.py`. `payload` holds `artifact` (the redacted transcript),
`modelResult`, `inference`, `job`, `epoch` and `policyDigest`.

## How records get there

`transcripts/infra/archive_sync.py` runs on the transcript host as its own systemd
units, separate from the relay and enclave services:

- `peer-link-transcript-archive-sync.path` starts a run when the host archive
  directory changes, so a record normally reaches S3 within a few seconds.
- `peer-link-transcript-archive-sync.timer` reruns every minute to pick up anything
  written during a run and to retry failed uploads.
- `peer-link-transcript-archive-sync.service` is the one-shot run. It is sandboxed
  with `ProtectSystem=strict`, so the host archive is read-only to it.

For each `<sha256>.json` it checks that the name equals the SHA-256 of the bytes,
parses the record, and builds both keys only from strictly validated fields: a
32-hex job ID, a known settlement state, and campaign and bank IDs in their policy
charsets. In-progress `.tmp` files, other names, symlinks, subdirectories and
records that fail any check are never uploaded. S3 verifies a SHA-256 checksum on
each upload. An empty marker under `/var/lib/peer-link-transcript-archive/uploaded/`
is written only after both objects are accepted, which makes reruns idempotent.
The journal receives a numeric summary only, never keys, job IDs or record content.

The script lives in `/opt/peer-link-transcript-archive/`, outside the release tree.
`install_release.sh` does not touch it or its units, and a briefly missing archive
directory during a release rollover is a clean no-op.

## Host permissions

The dedicated host role can write to the two prefixes and nothing else in S3. It
cannot read, list or delete, so a compromised host cannot inspect or remove records
that already left it. These statements are appended to the host role policy, and
`s3:PutObject` is added to its catch-all `NotAction` list
(`host_statements` in `transcripts/infra/archive_template.py`):

```json
[
  {
    "Sid": "WriteOnlyTranscriptArchive",
    "Effect": "Allow",
    "Action": "s3:PutObject",
    "Resource": [
      "arn:aws:s3:::peerlink-transcripts-411399509833/records/*",
      "arn:aws:s3:::peerlink-transcripts-411399509833/by-bank/*"
    ]
  },
  {
    "Sid": "DenyOtherArchiveWrites",
    "Effect": "Deny",
    "Action": "s3:PutObject",
    "NotResource": [
      "arn:aws:s3:::peerlink-transcripts-411399509833/records/*",
      "arn:aws:s3:::peerlink-transcripts-411399509833/by-bank/*"
    ]
  }
]
```

The live host role carries reviewed additive grants that `transcripts/infra/template.py`
does not generate. Change it by editing the live stack template additively and
reviewing a change set that shows one non-replacing `HostRole` modification. Do
not regenerate the host stack from `template.py`; that would drop those grants.

## Verify a job reached S3

Use an operator session, not the host:

```sh
aws s3 ls s3://peerlink-transcripts-411399509833/by-bank/<bankId>/<campaignId>/<jobId>/
```

Expect one object per settlement state. To check integrity, download the
content-addressed copy and compare its hash with its name:

```sh
aws s3 cp s3://peerlink-transcripts-411399509833/records/<sha256>.json .local/record.json
shasum -a 256 .local/record.json
```

The record digest is what the host acknowledged to the enclave. To authenticate a
record beyond that, verify its RSA-PSS `signature` over the canonical `payload`
against the receipt key from a fresh attested preflight, as
`transcripts.cli receipt` does for a contributor's own job.

On the host, `systemctl status peer-link-transcript-archive-sync.path` should be
`active (waiting)`, and
`journalctl -u peer-link-transcript-archive-sync.service` shows a line such as
`{"alreadyUploaded": 6, "failed": 0, "scanned": 7, "skipped": 0, "uploaded": 1}`
for each run that uploaded or failed. `skipped` counts files that are not valid
records; `failed` counts uploads that will be retried.

## Pull records for transformer work

```sh
aws s3 sync s3://peerlink-transcripts-411399509833/by-bank/<bankId>/ .local/transcript-archive/<bankId>/
```

Keep the download in ignored `.local/`. Records are redacted and contain no bank
values, but they are internal working material: do not commit them or attach them
to issues or PRs. Prefer the `paid` record of each job; it is the final state.

## Install or update the host units

Create the bucket once:

```sh
python3 transcripts/infra/archive_template.py > transcripts/infra/archive.cfn.json
aws cloudformation create-stack --stack-name peerlink-transcript-archive \
  --template-body file://transcripts/infra/archive.cfn.json
```

Then, through SSM on the dedicated transcript host, place `archive_sync.py` and
`install_archive_sync.sh` in a private temporary directory and run:

```sh
bash install_archive_sync.sh archive_sync.py <sha256 of archive_sync.py> peerlink-transcripts-411399509833 us-east-1
```

The host role cannot read S3, so ship both files inline in the SSM command rather
than by download, and compare the SHA-256 on the host. The installer validates its
arguments before changing anything, is safe to rerun, performs one mirror run, and
does not stop, restart or edit the relay, enclave, credential or health services.

## Limits

- The mirror is a copy, not an acknowledgment. The enclave pays after the host's
  fsync acknowledgment, not after the S3 upload. A record written just before a
  host loss can exist only on that host until the next run.
- An authorized operator can delete objects or versions. Versioning and `Retain`
  guard against accidents, not against an administrator.
- Upload markers are per host. A replacement host re-uploads identical bytes,
  which only adds an identical object version.
- If the relay's `--archive-dir` changes, update the path and service units to
  match; the default is `/var/lib/peer-link-transcripts/artifacts`.
