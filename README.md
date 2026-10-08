# Peer Link

A decentralized peer-to-peer networking protocol with Mercury transcript evidence tracking.

## Overview

Peer Link enables secure, transparent communication between nodes with built-in evidence tracking through the Mercury transcript system.

## Features

- **Mercury Transcript System**: Maintain evidence and coverage discussions during transcript-program migrations
- **Public Schema Support**: Standardized endpoint patterns for public data exchange
- **Decentralized Architecture**: No single point of failure or control

## Getting Started

```bash
# Clone the repository
git clone https://github.com/zkp2p/peer-link.git
cd peer-link

# Install dependencies
npm install

# Run tests
npm test
```

## Mercury Program

The Mercury program provides a framework for evidence/coverage discussions during transcript migrations.

### Contributing

To contribute transcripts:
1. Ensure an approved release is available
2. Reserve a slot in the active campaign
3. Follow the [Contribute Transcript Skill](./skills/contribute-transcript/SKILL.md)

### Important Notes

- Never share banking credentials, account identifiers, or raw records
- Only discuss public schema and endpoint patterns
- Historical technical issues do not create separate payable slots

## Repository Structure

```
peer-link/
├── skills/
│   └── contribute-transcript/
│       └── SKILL.md
├── tests/
│   └── transcript.test.js
├── package.json
└── README.md
```

## License

MIT
