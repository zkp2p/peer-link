# Contribute a banking transcript

The paid contribution is a value-free transcript of how your bank presents
transaction history, produced from your own account. Peer engineers build the
integration. You do not implement a provider, claim an issue by commenting, or
open a pull request.

## Start

Give your local agent the prompt in [README.md](README.md). It will follow
[skills/contribute-transcript/SKILL.md](skills/contribute-transcript/SKILL.md)
and [docs/transcript-recipes.md](docs/transcript-recipes.md). Read
[privacy](docs/privacy.md) and [reward terms](docs/incentives.md) yourself
first.

1. Find your bank with `campaigns --live`. Each campaign has a fixed $5 or $10
   USDC reward; all campaigns share one funded budget, so check that a slot and
   budget remain before you start.
2. Sign in to your bank yourself. Your agent finds the read-only JSON requests
   the bank's site uses to show your history and writes them into a recipe with
   notes for engineers.
3. Run `preview`. It replays the reads from your machine and prints everything
   that would be kept. Review it; if anything personal appears, stop.
4. Choose the model your own API key will pay for, on any OpenAI-compatible
   endpoint. You pay for one call even if the job is rejected.
5. Run `contribute`. The client verifies the enclave, reserves a job for ten
   minutes, and encrypts your recipe, session and inference key to the enclave.
   The enclave repeats the reads, redacts them, asks your model which fields
   carry payment details, verifies the answer in code, and pays the fixed
   reward to your Base address when it passes.
6. Keep the state file and poll `job` until it is paid or rejected. Then log
   out of the bank session, revoke any dedicated token and revoke or cap the
   inference key.

One contribution per bank account is paid per campaign. New wallets or GitHub
accounts do not make a new contributor. Mercury is a separate first-contributor
campaign for one organization using a read-only API token; see
[source validation](docs/source-validation.md). Wise has no public reward.

## Requests, bugs and repository maintenance

Propose a bank only if it has no campaign issue, using the bank-request
template. If your bank's API lives on a domain its campaign does not list, or a
read-only request is refused, say so on the bank's campaign issue with the
fixed reason code. Send vulnerabilities or exposures through
[SECURITY.md](SECURITY.md). Never attach raw captures, identifiers, screenshots,
API keys or request headers.

Service, documentation and synthetic regression fixes are normal code
maintenance and do not earn a transcript reward. Keep changes focused and
original, run the relevant credential-free checks, inspect the complete diff,
and run:

```sh
npm run privacy -- --staged
npm run privacy -- --range origin/main..HEAD
```

Synthetic fixtures must use invented values, not copied bank records. Existing
adapter tooling and its CI layout checks remain for reference assets and are
not a prerequisite for transcript contributions.

## Legacy contributions

The old provider program is retired. See its
[archived contribution guide](https://github.com/zkp2p/peer-link/blob/31bba0e6c55f41ff08f31d30e728e1ef41d38a3b/CONTRIBUTING.md) and
[archived award terms](https://github.com/zkp2p/peer-link/blob/31bba0e6c55f41ff08f31d30e728e1ef41d38a3b/docs/incentives.md) for historical context.
Legacy PRs may close with a program-change notice while their commits and
conversations remain available. Previously earned or accepted awards are preserved;
disputed earlier claims require review under the original written terms.
Do not reinterpret a legacy obligation using the new $5/$10 campaign rules.

Code contributions require rights to submit under MIT. Do not copy proprietary,
employer-owned or private Peer implementation code. Acceptance of evidence or code
does not enable a bank in Peer or certify settlement.
