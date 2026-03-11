"""
Firestore Data Schema Definitions with Pydantic Validation
Ensures type safety and schema consistency across components.
"""
from datetime import datetime
from typing import Dict, List, Optional, Union, Any
from pydantic import BaseModel, Field, validator
from enum import Enum


class ModelType(str, Enum):
    WEIGHTED_MATRIX = "weighted_matrix"
    THRESHOLD_RULES = "threshold_rules"
    REGRESSION = "regression"


class ApprovalStatus(str, Enum):
    LIVE = "live"
    PROPOSED = "proposed"
    ARCHIVED = "archived"
    CANDIDATE = "candidate"


class TreasuryState(BaseModel):
    """Validated treasury state with confidence scoring"""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    balances: Dict[str, float] = Field(..., description="Asset: balance mapping")
    market_data: Dict[str, Any] = Field(..., description="Prices, volumes, fees")
    confidence_score: float = Field(ge=0.0, le=1.0, default=1.0)
    anomaly_flags: List[str] = Field(default_factory=list)
    oracle_discrepancies: Dict[str, float] = Field(default_factory=dict)
    
    @validator('confidence_score')
    def validate_confidence(cls, v):
        return round(v, 4)  # Ensure consistent precision


class CoreContext(BaseModel):
    """Short-term memory buffer for trend analysis"""
    sequence_id: int
    timestamp: datetime
    state_input: Dict[str, Any]  # Reference to TreasuryState document ID
    decision_made: Dict[str, float]  # Allocation percentages
    model_used: str  # Model version ID
    context_tags: List[str] = Field(default_factory=list)


class StrategyModel(BaseModel):
    """Versioned strategy model with performance tracking"""
    model_id: str
    model_type: ModelType
    parameters: Dict[str, Any]
    version: str = "1.0.0"
    approval_status: ApprovalStatus
    performance_metrics: Dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_evaluated: Optional[datetime] = None
    
    @validator('model_id')
    def validate_model_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError("model_id cannot be empty")
        return v


class DecisionLog(BaseModel):
    """Immutable record of each decision cycle"""
    decision_id: str  # UUID
    timestamp: datetime
    input_state_ref: str  # Firestore document ID
    output_allocation: Dict[str, float]  # API: %, Spec: %, Infra: %
    model_version: str
    execution_receipt_ref: Optional[str] = None
    regret_metrics: Optional[Dict[str, float]] = None
    confidence_score: float = 1.0


class ExecutionReceipt(BaseModel):
    """Immutable record of execution outcomes"""
    receipt_id: str  # Matches decision_id
    timestamp: datetime
    actions: List[Dict[str, Any]]  # Each action with type, target, amount
    simulated_slippage: float
    actual_slippage: Optional[float] = None
    tx_hashes: List[str] = Field(default_factory=list)
    status: str = "pending"  # pending, success, failed, simulated
    error_log: Optional[str] = None
    retry_count: int = 0


class ControlState(BaseModel):
    """Global control and emergency state"""
    emergency_halt: bool = False
    halt_reason: Optional[str] = None
    halt_initiator: Optional[str] = None
    halt_timestamp: Optional[datetime] = None
    global_parameters: Dict[str, Any] = Field(default_factory=dict)
    system_mode: str = "normal"  # normal, learning, emergency