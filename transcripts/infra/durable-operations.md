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

The default finite guard and Restart=no remain active. The durable installer uses
`supervise_enclave.py` with Type=notify: it refuses an existing enclave, launches
CID16/2CPU/2048MiB, records the exact host-prefixed enclave ID and requires paused
policy-bound health within90seconds. After readiness it polls actual Nitro
liveness every5seconds. Startup/liveness failure cleans up only that ID; each
Nitro command is bounded30seconds and systemd stop allows75seconds. No terminate-all,
autoactivation, auto-funding or signed operator action is used. Transient HTTP
failures produce alarms instead of monitor-driven enclave replacement.

After durable hardware restore, budget/nonce/payout gates and deployment review:

1. Prepare a NEW-host-only CloudFormation change set from `template.py`, preserving
   the current resolved ImageId, network, payout key and exact StateAuthorityVersionArn,
   StateKeyArn and StateNamespace grants. `ContinuousServiceEnabled=true` requires
   all state/custody pins, disables only this stack's ExpirySchedule and removes its
   expiry-heartbeat alarm. Review for no EC2 replacement, no old-stack changes and
   only intended IAM/schedule/alarm changes before execution. Default false preserves
   finite RAM pilot behavior; NEVER apply this opt-out to the old funded RAM host.
2. After independent genuine quote/Recipient/CMS bootstrap + hardware restart proof,
   run `install_continuous.sh INSTANCE_ID REGION POLICY_DIGEST` on the reviewed NEW
   host with PEERLINK_CONTINUOUS_APPROVED equal to that digest. This workflow token
   records operator intent; it is not cryptographic release approval. Verify the
   finite guard was disabled and release approval completed separately. The helper
   checks paused durable policy-bound health, installs10second Restart=on-failure
   backoff/maximum3starts in300seconds and enables relay/credentials/enclave boot.
   On boot, allocator + relay listeners + credentials must be ready before enclave
   restore. Exhausted retries need operator attention. A helper-service outage may
   stop its dependent enclave; inspect/restart the group manually after correction.
3. Every restored runtime remains paused, preserving durable obligations, nonce
   witness, receipt key and logical epoch. Resume requires a fresh signed operator
   action after chain/head continuity checks. Unknown/fenced/pending state fails
   closed; do not initialize blank state, lower generation or discard obligations.
4. The separate health publisher checks only localhost public health (5second HTTP
   timeout) once per minute and emits RuntimeHealth/AdmissionsOpen numerical0/1
   metrics with InstanceId. AWS CLI is bounded20seconds/one attempt, uses only
   instance credentials and the official regional endpoint; overrides are removed.
   Role permission is only PutMetricData in PeerLink/Transcripts. Alarms trigger
   after3unhealthy/missing samples. Paused restore produces RuntimeHealth1 and
   AdmissionsOpen0, intentionally requesting manual signed resume. No request,
   credential, bank/model, ciphertext or private state payloads are logged or probed.
   No automatic reboot, activation or new notification subscription is configured.
   Without a tested AlarmTopicArn these are operator-supervised console alarms.
5. Before deliberate shutdown, close admissions, settle/reconcile obligations,
   preserve signed archives off-host and refund/recover with operator custody.
   Managed encrypted state survives host failure; one EC2 host still means downtime
   and manual recovery after start-limit exhaustion or an instance stop. HA, standby,
   automatic operator resume and generalized policy migration are optional later work.

Hardware evidence must demonstrate stable receipt key/logical epoch, fresh ingress,
writer-generation+1, monotonic revision, exact head/master binding and unchanged
zero-USDC/pending nonce anchor. Local tests cover stale capability/CAS fencing; do
not claim a hardware stale-writer rejection or submit synthetic negative commits to
the public namespace. Health metrics do not prove each commit or replace that proof.

CloudWatch namespace permission uses the documented
[namespace condition](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/iam-cw-condition-keys-namespace.html).

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
