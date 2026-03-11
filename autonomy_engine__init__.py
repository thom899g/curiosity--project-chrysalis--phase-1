"""
Autonomy Engine Core - Project Chrysalis Phase 1
A protected, interconnected, upgradeable system for autonomous treasury management.
Version: 1.0.0
"""
__version__ = "1.0.0"
__author__ = "Evolution Ecosystem - Curiosity Agent"

# Core component exports
from .perception_validation_layer import PerceptionValidationLayer
from .judgment_evolution_core import JudgmentEvolutionCore
from .autonomous_executor import AutonomousExecutor
from .outcome_analyzer import OutcomeAnalyzer
from .model_optimizer import ModelOptimizer
from .governance_circuit_breaker import GovernanceCircuitBreaker
from .data_schema import (
    TreasuryState,
    CoreContext,
    StrategyModel,
    DecisionLog,
    ExecutionReceipt,
    ControlState
)