```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Union

@dataclass
class MpesaTransaction:
    id: str
    amount: int
    currency: str
    payer: str
    payee: str
    status: str
    timestamp: str
    transaction_id: str
    amount_original: Optional[float] = None
    description: Optional[str] = None

class SafaricomMpesaAdapter:
    def adapt(self, data: dict) -> dict:
        return MpesaTransaction(
            id=data.get("id"),
            amount=int(round(data["amount"] * 100)),
            currency=data.get("currency", "KES"),
            payer=data.get("payer"),
            payee=data.get("payee"),
            status=data.get("status"),
            timestamp=datetime.fromisoformat(data["timestamp"]).isoformat(),
            transaction_id=data.get("transaction_id")
        )

# Example usage:
# data = {
#     "id": "123",
#     "amount": 1.0,
#     "currency": "KES",
#     "payer": "John Doe",
#     "payee": "Jane Smith",
#     "status": "completed",
#     "timestamp": "2024-01-01T12:00:00Z",
#     "transaction_id": "MP123456789"
# }
# adapter = SafaricomMpesaAdapter()
# transaction = adapter.adapt(data)
# print(transaction)
```