# Durable state deployment and recovery gates

These files prepare a new retained state stack alongside the dedicated KMS host.
They do not approve a public measured release, enable collection, fund a wallet,
restore an old RAM epoch or change the old funded host. The payout KMS key remains
operator recoverable; ordinary host/payout permissions cannot decrypt the separate
state secret. AWS/KMS policy administrators remain trusted to preserve authorization.

## Authority and secret flow

- Publish the reviewed `state_authority.py` as a numbered immutable Lambda version.
  Pin its full version ARN and source/code hashes; never pin `$LATEST` or an alias.
  Lambda runtime mode is FunctionUpdate. The host receives InvokeFunction only
  for that exact version and no DynamoDB write/delete access.
- Lambda alone uses GetItem with ConsistentRead=true and conditional UpdateItem
  on its exact table/namespace. Ciphertext and wrappedMaster use DynamoDB Binary
  attributes. Decoded ciphertext is capped at327680bytes and wrappedMaster6144;
  reject projected state growth before inference or payout side effects.
- Create is revision0/generation1 and conditionally absent only. Commit requires
  expected revision/digest/generation, advances revision exactly1, and keeps the
  generation or advances it exactly1 for a re-encrypted writer takeover. The
  wrapped master cannot change. Repeated lost-ack commits succeed only for the
  exact current opId/revision/generation/digest/ciphertext/nextcommitment.
- A head publishes only SHA256(k_revision). A commit reveals the secret preimage
  through enclave-terminated AWS TLS, hashes it inside Lambda and conditionally
  matches the old commitment. Lambda never logs/returns/stores the capability;
  DynamoDB receives only its hash. An Invoke-only host can deny availability or
  race initial creation, but cannot rewrite initialized state without that key.
- Use a separate symmetric ENCRYPT_DECRYPT KMS key. Its default template grants
  no cryptographic use while ApprovedImageSha384 is empty. Authorize only actual
  independently reviewed PCR0 and rolePCR3, and the exact Namespace context.
  Neither the host nor payout operators receive Encrypt, non-Recipient decrypt
  or GenerateDataKeyWithoutPlaintext. The exact image pin matters because the
  existing image signer is stored on the parent host.
- Enclave TLS/SigV4 authenticates fixed regional KMS and Lambda endpoints.
  CID16 obtains short-lived role credentials from CID3:5104, request `{version:1}`.
  Response fields are version/accessKeyId/secretAccessKey/sessionToken/expiration
  (Unixseconds)/roleArn/instanceId. They stay in RAM and are never diagnostic output.
  Separate ephemeral RSA2048 Recipient keys unwrap the actual KMS CMS envelope
  inside the enclave. The parent sees encrypted transport, not the master.
- Master context is Namespace/PolicyDigest/PayoutWallet/AuthorityArn; the sealed
  snapshot also binds schema, revision, writerGeneration and opId. Policy or
  namespace changes require reviewed migration; no automatic funded blank-ledger
  bootstrap. Persist budget, account dedup, operator replay protection, nonce/
  payout intent and exact pending signed transaction before any broadcast.
  Never persist bank/inference credentials or raw bank values. New boot challenges
  invalidate old ephemeral channel requests. Reconcile pending identities before
  allocating a new nonce; unknown external pending transactions fail closed.

## Reviewable bootstrap sequence

1. Generate `state.cfn.json` using `python3 transcripts/infra/state_template.py`.
   Supply the exact new host role ARN, SHA384(48zero bytes + ARN) as PCR3,
   dedicated namespace, and empty ApprovedImageSha384. Validate/create/review a
   change set and execute only after owner review. No head create/test writes in
   the real namespace; load/invalid namespace checks are read-only.
2. Verify the owning stack, retained table/PITR/deletion protection, key policy,
   live function source and actual CodeSha256, published numbered version,
   consistent empty load and fixed errors. Record exact resource/version ARNs.
3. `host_state_policy.py` prepares a full policy from the live host policy and
   exact version/key/namespace. It adjusts the existing DenyNotAction list, keeps
   payout/SSM grants, adds only exact-version invocation/Recipient key use, and
   denies other versions/keys and non-Recipient use. Review a live diff/simulation
   before applying; the script itself performs no IAM calls. Record intentional
   drift if direct IAM is used instead of an isolated CloudFormation role update.
4. Root embeds the actual public ARNs and credentialRoleArn in measured policy,
   builds the exact source, compares both independent CI builds, then signs it.
   Update ONLY state-key authorization with the genuine approved PCR0. Do not
   synthesize an approved release or authorize just the host-held image signer.
5. A durable `install_release.sh` invocation requires a fourth argument with the
   independently reviewed host instance ID. It starts the port5104 memory-only
   forwarder before enclave boot and adds the enclave service dependency. It
   still starts paused and uses Restart=no until the following lifecycle gate.
6. Verify genuine fresh Nitro quote/source/PCRs, actual Recipient GenerateDataKey/
   restore, private master never exposed, duplicate/replay/CAS/fence rejection,
   lost acknowledgement and process-crash boundaries, exact pending-payout
   reconciliation and preservation of old paid archive proofs. Publish authority/
   state/privacy evidence alongside the independent release authority after review.

## Continuous service plan: prepare, do not apply to the pilot

The installer starts memory-only credentials and the host relay before the enclave.
Both are Type=notify: credential readiness means5104 has bound/listened; relay
readiness means5101/5102/5103 and HTTP have bound/listened. Only their main process
sends READY, after a bounded startup check. Bind failure prevents enclave startup;
HTTP returns unavailable until the enclave runtime finishes authenticated restore.

The authority role's only non-DynamoDB exception is Decrypt on the independently
verified AWS-managed Lambda environment key. Lambda needs this before its handler
starts; the key's managed policy restricts Lambda origin/context. Explicit deny
on every other decrypt key includes the separate state-master key. Set the exact
LambdaEnvironmentKeyArn parameter after verifying KeyManager=AWS and aws/lambda.
Published authority and $LATEST runtime management must independently report
FunctionUpdate; CloudFormation import does not apply unchanged configuration.

The current finite guard and Restart=no remain active. After durable hardware
restore, budget/nonce/payout gates and explicit deployment review:

1. On ONLY the new KMS host, add service drop-ins for enclave/relay/credentials
   with Restart=on-failure, bounded RestartSec and StartLimitBurst; enable the
   units with the credential -> enclave -> relay dependency order. An enclave
   process needs an actual liveness/watchdog check: its oneshot launcher remains
   active after launch and Restart alone does not detect a dead enclave.
2. Startup acquires a new writer generation and restores/reconciles the durable
   head before accepting jobs. Service restarts must not create another funded
   logical ledger or accept blank state. An expired/fenced/error head pauses
   admissions/payments; persisted exact transactions may be reconciled.
3. Remove only the new stack's finite ExpirySchedule through a reviewed change
   set. Do not change the old ephemeral-wallet stop guard. Retain a deliberate
   shutdown path: close admissions, settle/reconcile obligations, archive and
   refund/recover under operator custody before stopping.
4. Add payload-free health/last-durable-commit-age and restore/fence/error counts.
   Prefer existing AWS/DynamoDB ConditionalCheckFailedRequests/UserErrors and
   AWS/Lambda Errors/Throttles alarms plus authenticated public-health probes.
   A successful Lambda Invoke can still return state_unavailable, so native
   Lambda Errors alone is insufficient. No secrets/headers/ciphertext/request
   bodies in counters or logs. Do not invent SNS subscriptions; use only an
   established, tested destination or clearly supervised alarms with no actions.
5. Keep a capped single-writer rollout. One EC2 host is an availability dependency,
   despite multi-AZ managed state. A later second-AZ standby needs demonstrated
   fencing and exact-payout recovery, never active-active wallet signing.

## Backups and rollback

State table/key/function/version/role retain on stack deletion/replacement, PITR
is35days, and the table has deletion protection. No TTL on dedup/payment/nonce
authority. Ciphertext backup without the retained KMS key is unusable; protect
key disable/deletion, inspect retention and test a restore independently.

PITR restores to a new table; never point the public authority at an older head
or overwrite the live revision. Restored state is for review/chain reconciliation
and an explicitly approved migration. Code rollback may use only a reviewed image
whose format/policy remains compatible with the latest head; it cannot lower the
revision/generation or bypass KMS image authorization. Preserve signed paid archives,
old public quotes and manifests off-host independently of operational snapshots.

Primary references: [KMS Recipient decrypt](https://docs.aws.amazon.com/kms/latest/APIReference/API_Decrypt.html),
[Recipient GenerateDataKey](https://docs.aws.amazon.com/kms/latest/APIReference/API_GenerateDataKey.html),
[Nitro key conditions](https://docs.aws.amazon.com/kms/latest/developerguide/conditions-nitro-enclave.html),
[DynamoDB consistency](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html),
[binary item limits](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Constraints.html),
[PITR](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Point-in-time-recovery.html),
[Lambda versions](https://docs.aws.amazon.com/lambda/latest/dg/configuration-versions.html).
