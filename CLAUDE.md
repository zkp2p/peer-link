# PeerLink agent entrypoint

Read AGENTS.md first. To help someone contribute a banking transcript, follow skills/contribute-transcript/SKILL.md and docs/transcript-recipes.md. Recover an existing job before starting another. Finish setup, attestation/capacity checks and inference access before asking the owner to sign in; then write a read-only recipe, preview it, get consent for the exact terms, and contribute. A verified paid receipt completes the contribution or end-to-end test. Creating integrations, campaigns, pull requests or deployments is separate maintainer work. Provider-code bounties are retired.


## Required logos for main-page integrations

Whenever you add a bank to the main page, add its actual logo in the same change. Do not ship missing/null logos or initials-only placeholders.

- Store the unchanged logo in `app/public/logos/` and document its official public source in `app/public/logos/BANK-ASSETS.md`. Do not hotlink images or copy private assets.
- Set the local logo path in `app/banks.json` and any corresponding `app/bounties.json` entry. Ensure catalog-backed adapters also resolve their logo in `app/main.ts`.
- Keep the first four cards ordered Mercury, Chase, Bank of America, Wells Fargo unless the user directs otherwise. Preserve all other bank entries.
- Inspect the rendered logos on desktop and mobile, run the repository checks, and run `npm run privacy -- --staged` before publishing.
