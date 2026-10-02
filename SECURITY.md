# Security

Do not use experimental parser results alone to release money. Inputs are unauthenticated. No hosted bank-session processing or signing service exists here.

Report vulnerabilities or exposed data through [GitHub private vulnerability reporting](https://github.com/zkp2p/peer-link/security/advisories/new) on this repository. If unavailable, email 0xsachink@gmail.com with a minimal description, not credentials or raw banking data. Avoid public issues for exploit details or personal records.

CI runs on disposable GitHub-hosted runners, with read-only contents permissions, no repository secrets, no credential persistence, no `pull_request_target`, no self-hosted runners and no live bank sessions. Dependencies install with lifecycle scripts disabled. Dependency updates and workflow changes require code-owner review.

Contributor code is untrusted. Pull-request CI executes adapter tests, so it must never gain secrets or write tokens. `npm run validate` rejects impure adapter constructs (imports, network, timers, logging, clock and locale use) and, for pull requests from forks, new files outside a bank folder; these static checks catch mistakes, not determined attackers. Because a pull request can also modify the checks themselves, reviewers rerun `main`'s checks on changes to `scripts/`, `lib/`, configuration or workflows (see the review skill). Public build artifacts contain only the landing page and public catalog.
