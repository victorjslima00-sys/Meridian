from typing import Dict, Any

class RiskManager:
    def __init__(self, current_capital: float, win_rate: float = 0.55, win_loss_ratio: float = 1.5):
        self.current_capital = current_capital
        self.win_rate = win_rate
        self.win_loss_ratio = win_loss_ratio
        
    def calculate_position_size(self, risk_per_trade: float = 0.02) -> float:
        """
        Uses the Kelly Criterion (simplified) to determine optimal position size.
        """
        kelly_pct = self.win_rate - ((1 - self.win_rate) / self.win_loss_ratio)
        # Cap the max risk to avoid ruin
        safe_kelly = min(kelly_pct * 0.5, risk_per_trade) 
        
        if safe_kelly < 0:
            return 0.0 # Algorithm says do not trade
            
        return self.current_capital * safe_kelly

    def evaluate_trade(self, analyst_signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Takes the market analyst's signal and decides if we should execute.
        """
        if analyst_signal['signal'] == "HOLD":
            return {"approved": False, "reason": "Analyst recommends HOLD."}
            
        pos_size = self.calculate_position_size()
        
        if pos_size <= 0:
            return {"approved": False, "reason": "Risk Manager veto: Kelly criterion suggests 0 allocation."}
            
        return {
            "approved": True,
            "allocated_capital": pos_size,
            "reason": f"Trade approved. Allocating R$ {pos_size:.2f} based on risk limits."
        }
