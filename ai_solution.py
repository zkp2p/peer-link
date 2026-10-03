```json
{
  "$schema": "https://terminal.merit.systems/zkp2p/peer-link/schemas/adapter.json",
  "adapter": {
    "version": "1.0.0",
    "manifest": {
      "name": "Bank of America Adapter",
      "description": "Adapter for Bank of America integration.",
      "type": "bank"
    },
    "acquire": {
      "bank": "bank-of-america",
      "country": "us",
      "currency": "usd",
      "types": ["ach"],
      "method": "GET",
      "url": "https://api.bankofamerica.com/transactions",
      "headers": {
        "Accept": "application/json",
        "Content-Type": "application/json"
      },
      "params": {
        "accountId": "{accountId}"
      },
      "result": {
        "type": "array",
        "path": "$.transactions.transaction"
      }
    },
    "transform": {
      "function": "bankOfAmericaTransform",
      "params": {}
    }
  },
  "examples": {
    "ACH-001": {
      "bank": "bank-of-america",
      "country": "us",
      "currency": "usd",
      "type": "ach",
      "data": {
        "transactionId": "0012345678",
        "amount": {
          "value": 100.5,
          "currency": "USD"
        },
        "date": "2024-01-01T12:00:00Z",
        "status": "Cleared",
        "memo": "Payment for goods"
      }
    }
  },
  "notes": {
    "amount": {
      "unit": "USD",
      "precision": "cents"
    },
    "date": {
      "format": "ISO 8601"
    },
    "status": {
      "options": ["Pending", "Cleared", "Posted"]
    }
  }
}
```