# Sacombank (`vn/sacombank`) Adapter

Pure, read-only transaction interpreter for Saigon Thuong Tin Commercial Joint Stock Bank (Sacombank) Vietnam.

## Scope & Capabilities
- **Surface**: `web-portal-transaction-history` (https://isacombank.com.vn or official Sacombank eBanking)
- **Supported transfers**: Completed outgoing domestic VND account and Napas 247 fast transfers.
- **Currencies**: `VND` (exponent 0).
- **Security & Privacy**: Zero credentials, pure deterministic interpretation, no network calls or replay capability.

## Unsupported
- Scheduled / recurring transfers
- Bill payments & QR merchant purchases
- Incoming payments & cross-border remittances
- Recipient final settlement guarantee
