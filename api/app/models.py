from decimal import Decimal
from enum import Enum
from pydantic import AwareDatetime, BaseModel, Field

class TransactionType(str, Enum):
    WITHDRAWAL = "withdrawal"
    DEPOSIT = "deposit"
    TRANSFER = "transfer"

class Location(BaseModel):
    city: str
    country: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

class TransactionIn(BaseModel):
    account_id: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    transaction_type: TransactionType
    location: Location
    timestamp: AwareDatetime

class Status(str, Enum):
    APPROVED = "approved"
    FLAGGED = "flagged"

class FlagReason(str, Enum):
    LARGE_WITHDRAWAL = "LARGE_WITHDRAWAL"
    IMPOSSIBLE_TRAVEL = "IMPOSSIBLE_TRAVEL"
    EXCESSIVE_FAILED_LOGINS = "EXCESSIVE_FAILED_LOGINS"

class TransactionResult(BaseModel):
    transaction_id: str
    status: Status
    reasons: list[FlagReason]

class LoginAttempt(BaseModel):
    account_id: str = Field(min_length=1)
    success: bool
    timestamp: AwareDatetime

class FlaggedTransactionEvent(BaseModel):
    transaction_id: str
    reasons: list[FlagReason]
    evaluated_at: AwareDatetime
    transaction: TransactionIn