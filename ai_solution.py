```json
{
  "manifest": {
    "name": "kaspi_bank",
    "version": "1.0.0"
  },
  "adapter": {
    "name": "kaspi_bank",
    "version": "1.0.0",
    "methods": {
      "getTransactions": {
        "description": "Returns the list of transactions for the Kaspi Bank account.",
        "parameters": {},
        "function": "function getTransactions(response) {\n  const transactions = [];\n  const data = response.data;\n  if (data) {\n    data.forEach(transaction => {\n      const t = {\n        \"payer_id\": transaction.payer.id,\n        \"payee_id\": transaction.payee.id || transaction.payee.name,\n        \"amount\": {\n          \"amount\": Number(transaction.amount).toFixed(2),\n          \"currency\": \"KZT\"\n        },\n        \"status\": transaction.status === 'completed',\n        \"timestamp\": new Date(transaction.timestamp).toISOString(),\n        \"transaction_id\": transaction.transactionId\n      };\n      transactions.push(t);\n    });\n  }\n  return transactions;\n}"
      }
    }
  },
  "synthetic_fixtures": {
    "examples": [
      {
        "input": {
          "data": [
            {
              "payer": {
                "id": "123456789",
                "name": "John Doe"
              },
              "payee": {
                "id": "987654321",
                "name": "Jane Smith"
              },
              "amount": "10000.00",
              "currency": "KZT",
              "status": "completed",
              "timestamp": "2023-10-05T12:34:56Z",
              "transactionId": "T12345"
            }
          ]
        },
        "output": {
          "transactions": [
            {
              "payer_id": "123456789",
              "payee_id": "987654321",
              "amount": {
                "amount": "10000.00",
                "currency": "KZT"
              },
              "status": true,
              "timestamp": "2023-10-05T12:34:56Z",
              "transaction_id": "T12345"
            }
          ]
        }
      }
    ]
  },
  "notes": {
    "currency": "KZT",
    "status": "final",
    "time_zone": "UTC"
  }
}
```