# Peer Link naming migration

Peer Link is the project formerly called OpenPlaid and, briefly, OpenPeer. The
canonical public repository is `zkp2p/peer-link`; GitHub retains redirects from
the earlier repository URLs. The npm workspace name is `peer-link`.

Public copy, contribution links, agent instructions, catalog generation,
workflow variables, future infrastructure names and verifier identifiers use
the new name. The discovery document is `/.well-known/peer-link.json`; Vercel
redirects the two old discovery paths to it. The canonical public site is
`https://link.peer.xyz`; the earlier `openplaid.com` domain is a legacy address
only and is not the project name.

## Verification compatibility

This is a new verifier candidate. Session protocol names, permit/challenge
and receipt audiences, receipt signature domain, Wasm export name, image
metadata and container paths have changed together. Clients and workers must
use the same newly reviewed release. Old permits and sessions are not accepted
under the new names. Do not mix old and new artifacts or reuse old measurements.
Live verification remains disabled pending release approval and fresh validation.

Historical evidence in `verification/infra/evidence/` is immutable: it describes
the exact old source, resources, measurements and signatures that were tested.
It does not certify this renamed candidate. Copyright notices retain original
attribution. Existing audit records and retained AWS resource IDs also retain
their historical names; renaming source templates does not migrate a live stack.
The old controller was shut down before this migration. Reaper tag selectors
and IAM resource-tag conditions must always be deployed as one reviewed unit.

## Hosting ownership and rollback

The existing landing project has moved into Peer's Vercel team with its
deployments, domains and rollback history. Its stable project ID, Peer ownership
and GitHub `zkp2p/peer-link` connection were verified. The transfer removes the
project from the personal scope; do not delete the transferred project or its
rollback deployment. Keep Git-triggered deploys disabled until
a reviewed release is explicitly promoted. The public site takes no bank input.
