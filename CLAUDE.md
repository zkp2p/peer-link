# PeerLink agent entrypoint

Read AGENTS.md and skills/contribute-transcript/SKILL.md. The active contribution program collects attested banking transcripts; provider-code bounties are retired.


## Required logos for main-page integrations

Whenever you add a bank to the main page, add its actual logo in the same change. Do not ship missing/null logos or initials-only placeholders.

- Store the unchanged logo in `app/public/logos/` and document its official public source in `app/public/logos/BANK-ASSETS.md`. Do not hotlink images or copy private assets.
- Set the local logo path in `app/banks.json` and any corresponding `app/bounties.json` entry. Ensure catalog-backed adapters also resolve their logo in `app/main.ts`.
- Keep the first four cards ordered Mercury, Chase, Bank of America, Wells Fargo unless the user directs otherwise. Preserve all other bank entries.
- Inspect the rendered logos on desktop and mobile, run the repository checks, and run `npm run privacy -- --staged` before publishing.
