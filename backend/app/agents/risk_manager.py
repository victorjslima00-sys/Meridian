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
            
        current_price = analyst_signal.get('last_price', 0.0)
        
        # Simple risk reward ratio 1:3 for targets
        target_price = 0.0
        stop_loss = 0.0
        
        if current_price > 0:
            if analyst_signal['signal'] == "BUY":
                target_price = current_price * 1.06 # 6% target
                stop_loss = current_price * 0.98    # 2% stop
            elif analyst_signal['signal'] == "SELL":
                target_price = current_price * 0.94 # 6% target
                stop_loss = current_price * 1.02    # 2% stop
                
        return {
            "approved": True,
            "allocated_capital": pos_size,
            "target_price": target_price,
            "stop_loss": stop_loss,
            "reason": f"Trade approved. Allocating R$ {pos_size:.2f} base na volatilidade."
        }
