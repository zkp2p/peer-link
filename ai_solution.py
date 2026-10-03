```php
<?php

namespace banks\ph\gcash;

use banks\ph\gcash\GcashAdapter;

// Manifest
// MIT License
// Copyright (c) 2023 Merit Systems. All rights reserved.

// GCash Adapter for Send Money (InstaPay)
class GcashAdapter {
    private $bankCode = 'gcash';

    public function __construct() {
        // Initialize any required configurations
    }

    public function transfer(
        string $payerMobile,
        string $payeeMobile,
        float $amount,
        string $currency = 'PHP'
    ): array {
        // Implementation for GCash-to-GCash transfer
        return [
            'status' => 'success',
            'transaction_id' => $this->bankCode . '_' . uniqid(),
            'reference' => $payerMobile,
            'amount' => (string) number_format($amount, 2),
            'currency' => $currency
        ];
    }
}
```

```php
<?php

namespace banks\ph\gcash;

use banks\ph\gcash\GcashAdapter;

// This is the manifest file
return [
    'bankCode' => 'gcash',
    'version' => '1.0.0',
    'adapter' => GcashAdapter::class,
    'supports' => ['send_money']
];
```