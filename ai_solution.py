To solve this task, we need to build an adapter for Wells Fargo to support one type of transfer, specifically Zelle. The goal is to create a function that captures the required details of a Zelle transfer from Wells Fargo.

### Approach
The task requires creating a function that captures the details of a Zelle transfer from Wells Fargo. The function should include the necessary information such as the bank name, transfer type, amount, currency, payer, payee, transaction ID, status, and timestamp.

### Solution Code
```python
from datetime import datetime

def wells_fargo_adapter(activity):
    """Wells Fargo Zelle adapter for a completed transfer."""
    # Required fields
    bank_name = "Wells Fargo"
    transfer_type = "Zelle"
    amount = activity["amount"]
    currency = "USD"
    
    # Determine payer and payee
    if activity["direction"] == "sent":
        payer = activity["account"]
        payee = activity["payee"]
    else:
        payer = activity["account"]
        payee = activity["payee"]
    
    # Required identifiers and status
    transaction_id = activity.get("transaction_id")
    status = "completed"
    timestamp = datetime.now().isoformat()
    timezone = "UTC"

    return {
        "bank": bank_name,
        "transfer_type": transfer_type,
        "amount": amount,
        "currency": currency,
        "payer": payer,
        "payee": payee,
        "transaction_id": transaction_id,
        "status": status,
        "timestamp": timestamp,
        "timezone": timezone
    }

# Test case
test_activity = {
    "activity": "Zelle transfer",
    "amount": "100.00",
    "currency": "USD",
    "direction": "sent",
    "account": "Wells Fargo Account",
    "payee": "Recipient Name",
    "transaction_id": "WELL123456"
}

result = wells_fargo_adapter(test_activity)
print(result)
```

### Explanation
The provided code defines a function `wells_fargo_adapter` that captures the details of a Zelle transfer from Wells Fargo. The function takes an activity dictionary as input and returns a dictionary with the required fields. The test case demonstrates how the function works with a sample input.