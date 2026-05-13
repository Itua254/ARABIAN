import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


class TradeState:
    INIT         = "init"
    VALIDATED    = "validated"
    EXECUTING    = "executing"
    PLACING_LEG_1 = "placing_leg_1"
    HEDGING_LEG_2 = "hedging_leg_2"
    PARTIAL_FILL = "partial_fill"
    HEDGING      = "hedging"      # v5 §3.2 — active hedge in flight
    SUCCESS      = "success"
    FAILED       = "failed"
    FINAL        = "final"

    # Transition validity map — used by Trade.transition()
    VALID_TRANSITIONS: Dict[str, List[str]] = {
        "init":          ["validated", "failed"],
        "validated":     ["executing", "failed"],
        "executing":     ["placing_leg_1", "failed"],
        "placing_leg_1": ["hedging_leg_2", "partial_fill", "failed"],
        "hedging_leg_2": ["success", "partial_fill", "failed"],
        "partial_fill":  ["hedging", "failed"],
        "hedging":       ["success", "failed"],
        "success":       ["final"],
        "failed":        ["final"],
        "final":         [],
    }


class ExecResult:
    FULL_SUCCESS = "full_success"
    PARTIAL_LEG1 = "partial_leg1"
    PARTIAL_LEG2 = "partial_leg2"
    TOTAL_FAIL   = "total_fail"


@dataclass
class Trade:
    """
    First-class trade object. v5 §3.4.
    Carries the full arb payload and its lifecycle state.
    """
    event_id:   str
    arb:        Dict[str, Any]
    state:      str = field(default=TradeState.INIT)
    created_at: float = field(default_factory=time.time)
    result:     Optional[str] = None
    legs_placed: List[int] = field(default_factory=list)  # indexes of placed legs
    error:      Optional[str] = None

    def transition(self, new_state: str) -> bool:
        """
        Moves the trade to a new state if the transition is valid.
        Returns True on success, False if invalid (won't raise, just logs).
        """
        allowed = TradeState.VALID_TRANSITIONS.get(self.state, [])
        if new_state in allowed:
            self.state = new_state
            return True
        return False

    def is_terminal(self) -> bool:
        return self.state == TradeState.FINAL

    def summary(self) -> Dict[str, Any]:
        return {
            "event_id":    self.event_id,
            "state":       self.state,
            "result":      self.result,
            "match":       self.arb.get("match"),
            "margin_pct":  self.arb.get("margin_pct"),
            "profit":      self.arb.get("profit"),
            "created_at":  self.created_at,
            "error":       self.error,
        }


class RiskLedger:
    """Tracks global capital exposure per active trade."""

    def __init__(self):
        # Maps event_id -> trade summary dict
        self.active: Dict[str, Any] = {}

    def register(self, event_id: str, trade_data: Any) -> None:
        """Registers a trade as active to lock capital exposure."""
        self.active[event_id] = trade_data

    def clear(self, event_id: str) -> None:
        """Removes a trade from the active ledger once resolved."""
        self.active.pop(event_id, None)

    def total_exposure(self) -> float:
        """Returns the sum of all active stakes."""
        total = 0.0
        for trade in self.active.values():
            legs = trade.get("arb", {}).get("legs", []) if "arb" in trade else []
            total += sum(leg.get("stake", 0) for leg in legs)
        return total
