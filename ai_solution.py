```javascript
// banks/mx/bbva-mexico/manifest.json
{
  "bank": "BBVA Mexico",
  "supported_transaction_types": ["transfer"],
  "currency": "MXN"
}

// banks/mx/bbva-mexico/adapter.js
import { Bank } from "@z KP2P";

const BBVAMexico = {
  name: "BBVA Mexico",
  country: "MX",
  currency: "MXN",
  adapters: {
    transfer: {
      parseAmount: ({ value }) => ({ amount: parseFloat(value), currency: "MXN" }),
      getTransactionId: ({ clave_de_rastreo }) => ({ transaction_id: clave_de_rastreo }),
      status: {
        pending: "Pendiente",
        completed: "Completado",
        failed: "Fallido"
      },
      timestamp: {
        format: "YYYY-MM-DD HH:mm:ss"
      }
    }
  }
};

// banks/mx/bbva-mexico/fixtures.js
const BBVAMexico_SPEI = {
  base: {
    amount: "100.50",
    currency: "MXN",
    transaction_id: "BBVA-TRANSFER-123456789"
  },
  valid: [
    {
      surface: "app",
      transaction: "transfer",
      data: {
        clave_de_rastreo: "BBVA-TRANSFER-123456789",
        monto: "100.50"
      }
    }
  ],
  negatives: [
    {
      surface: "web",
      transaction: "transfer",
      data: {
        clave_de_rastreo: "BBVA-TRANSFER-123456789",
        monto: "100.5"
      }
    },
    {
      surface: "app",
      transaction: "transfer",
      data: {
        clave_de_rastreo: "BBVA-TRANSFER-123456789"
      }
    }
  ]
};
```