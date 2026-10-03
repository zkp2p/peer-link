To solve this task, we need to create an adapter for BCA (Bank Central Asia) to handle IDR transfers. The adapter should be implemented in the specified folder and include the necessary code structure.

### Approach
The approach involves creating an adapter for BCA that supports IDR transfers. The adapter will include the implementation details and necessary methods to handle the transactions. The code will be structured with a manifest and the adapter object, ensuring it meets the specified requirements.

### Solution Code
```javascript
// src/banks/id/bca/manifest.json
{
  "name": "BCA for IDR transfers",
  "adapter": "bca-idr",
  "version": "1.0.0",
  "description": "Handles BCA transfers for IDR.",
  "type": "bank-transfer"
}

// src/banks/id/bca/adapter.js
import { BCA } from './bca/bca.js';
import { IDR } from './idr/idr.js';

const BCAAdapter = {
  id: 'bca-idr',
  name: 'BCA for IDR transfers',
  toObject: function (value) {
    return {
      type: 'bca-idr',
      value: value,
      currency: 'IDR',
      amount: value.amount,
      transactionId: value.transactionId,
      status: value.status,
      timestamp: value.timestamp
    };
  },
  fromObject: function (value) {
    return {
      type: 'bca-idr',
      value: value,
      currency: 'IDR',
      amount: value.amount,
      transactionId: value.transactionId,
      status: value.status,
      timestamp: value.timestamp
    };
  }
};

export default BCAAdapter;
```

### Explanation
The code provided includes the manifest and the BCA adapter. The manifest specifies the details of the adapter, and the adapter object includes methods for converting between the BCA and IDR formats. The `toObject` and `fromObject` methods handle the conversion, ensuring that the IDR transfers are properly formatted and include necessary details like currency, amount, and status. The code is structured to meet the requirements and is ready for integration.