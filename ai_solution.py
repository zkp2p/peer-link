To solve this problem, we need to build an OPay adapter that can handle NGN transfers. The adapter should be structured to extract and format transaction details from OPay transactions into a consistent format.

### Approach
The approach involves creating an adapter that reads the transaction details from OPay and formats them into a structured format. The adapter will include a manifest to describe its version and a handler function to process the transaction data.

### Solution Code
```javascript
import {Adapter} from 'bank-adapter';
import {Transaction} from 'types';

const OPAY_ADAPTER_VERSION = '1.0.0';

export const OPayAdapter = () => {
  return {
    name: 'OPayAdapter',
    version: OPAY_ADAPTER_VERSION,
    manifest: () => ({
      version: OPAY_ADAPTER_VERSION,
      handlers: ['handleTransaction'],
    }),
    handleTransaction: (transaction: any) => {
      return {
        amount: {
          value: transaction.amount,
          currency: transaction.currency,
        },
        payer: {
          id: transaction.payerAccountId,
          type: 'OPay',
        },
        payee: {
          id: transaction.payeeAccountId,
          type: 'OPay',
        },
        transactionId: transaction.transactionId,
        status: transaction.status,
        timestamp: new Date(transaction.timestamp).toISOString(),
        bank: 'OPay',
      };
    },
  };
};
```

### Explanation
The solution creates an OPayAdapter that processes OPay transactions. It includes a manifest describing the adapter's version and a handler function that formats the transaction data into a structured format. The handler function extracts key details such as amount, currency, payer, payee, transaction ID, status, and timestamp, ensuring the data is consistent and well-formatted.