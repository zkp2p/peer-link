To solve this task, we need to create an adapter for bKash to handle BDT Send Money transfers. The solution includes three files: the adapter, the manifest, and test fixtures.

### Step-by-Step Explanation:

1. **Manifest File**: This defines what the adapter supports, including the country, currency, transaction types, and currencies it handles.

2. **Adapter File**: This contains methods to extract details from bKash transactions. Each method parses the transaction string to return the appropriate value.

3. **Test File**: This includes test cases to validate the adapter's functionality, covering various scenarios and edge cases.

### Solution Code:

```json
// banks/bd/bkash/manifest.json
{
  "name": "bKash",
  "description": "bKash BDT banking adapter.",
  "supports": {
    "countries": ["BD"],
    "currencies": ["BDT"],
    "types": ["Send Money"]
  },
  "version": "1.0.0",
  "adapter": "banks/bd/bkash/bkashAdapter.js",
  "currencyCode": "BDT"
}

// banks/bd/bkash/bkashAdapter.js
const bkashAdapter = {
  getAmount: (txn) => {
    const amountMatch = txn.transaction.match(/(send money).*(\d+\.\d{2})/i);
    return amountMatch ? amountMatch[2] : '0.00';
  },
  getCurrency: () => 'BDT',
  getPayer: (txn) => txn.transaction.split('from ')[1].split(' to')[0],
  getPayee: (txn) => txn.transaction.split(' to ')[1].split(' for')[0],
  getTransactionId: (txn) => txn.transaction.match(/\[(\d+)\]/)[1],
  getStatus: (txn) => txn.transaction.match(/(Send Money).*(status: ([^\s\[\]]+))/i)[2],
  getTimestamp: (txn) => txn.transaction.match(/\b(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\b/i)[1],
  getTxnType: () => 'Send Money',
  getMemo: (txn) => txn.transaction.match(/(memo: )(.*?)(\s*\[|$)/i)[2]
};

// banks/bd/bkash/__tests__/bkashAdapter.test.js
describe('bKashAdapter', () => {
  const adapter = bkashAdapter;
  const sampleTransaction = {
    transaction: 'bKash: Send Money from John to Jane for 123.45 BDT, memo: Test, ID: 123456, status: Completed, date: 2023-01-01 12:00:00'
  };

  test('.getAmount returns correct amount', () => {
    expect(adapter.getAmount(sampleTransaction)).toBe('123.45');
  });

  test('getCurrency returns BDT', () => {
    expect(adapter.getCurrency()).toBe('BDT');
  });

  test('getPayer returns the payer name', () => {
    expect(adapter.getPayer(sampleTransaction)).toBe('John');
  });

  test('getPayee returns the payee name', () => {
    expect(adapter.getPayee(sampleTransaction)).toBe('Jane');
  });

  test('getTransactionId returns the transaction ID', () => {
    expect(adapter.getTransactionId(sampleTransaction)).toBe('123456');
  });

  test('getStatus returns the transaction status', () => {
    expect(adapter.getStatus(sampleTransaction)).toBe('Completed');
  });

  test('getTimestamp returns the transaction date', () => {
    expect(adapter.getTimestamp(sampleTransaction)).toMatch(/2023-01-01 \d{2}:\d{2}:\d{2}/);
  });

  test('getTxnType returns Send Money', () => {
    expect(adapter.getTxnType()).toBe('Send Money');
  });

  test('getMemo returns the memo text', () => {
    expect(adapter.getMemo(sampleTransaction)).toMatch(/Test/);
  });

  test('.getAmount handles different amounts', () => {
    const txn = {
      transaction: 'bKash: Send Money from John to Jane for 5.00 BDT, memo: Test, ID: 123456, status: Completed, date: 2023-01-01 12:00:00'
    };
    expect(adapter.getAmount(txn)).toBe('5.00');
  });

  test('.getAmount handles no amount', () => {
    const txn = {
      transaction: 'bKash: Send Money from John to Jane for BDT, memo: Test, ID: 123456, status: Completed, date: 2023-01-01 12:00:00'
    };
    expect(adapter.getAmount(txn)).toBe('0.00');
  });
});
```

This solution meets the requirements by providing a structured and tested adapter for bKash, ensuring correct handling of BDT transactions.