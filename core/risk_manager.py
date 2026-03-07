"""
Risk Manager
Handles position sizing, risk limits, and Alpha Shield circuit breaker.

Features:
- Fixed fractional position sizing
- Maximum position limits
- Drawdown tracking (Alpha Shield)
- VIX-adjusted sizing
- Correlation checks (future)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Dict
from enum import Enum

from config.settings import (
    RISK_PER_TRADE,
    MAX_POSITION_SIZE_PCT,
    MAX_POSITIONS,
    ALPHA_SHIELD_DRAWDOWN,
    BASE_CAPITAL
)
from filters.vix_filter import VixFilter, VixRegime

logger = logging.getLogger(__name__)


class RiskStatus(Enum):
    """Overall risk status."""
    NORMAL = "normal"
    CAUTION = "caution"  # Elevated VIX or approaching limits
    RESTRICTED = "restricted"  # Near drawdown limit
    BLOCKED = "blocked"  # Alpha Shield triggered


@dataclass
class RiskLimits:
    """Current risk limits and usage."""
    max_positions: int
    current_positions: int
    positions_available: int
    
    max_position_value: float
    current_exposure: float
    exposure_pct: float
    
    drawdown_limit: float
    current_drawdown: float
    drawdown_pct: float
    
    risk_per_trade: float
    vix_multiplier: float
    adjusted_risk: float
    
    status: RiskStatus
    status_reason: str


@dataclass
class PositionSizeResult:
    """Result of position size calculation."""
    shares: int
    position_value: float
    risk_amount: float
    risk_per_share: float
    
    is_valid: bool
    rejection_reason: Optional[str] = None
    
    # Adjustments applied
    vix_adjusted: bool = False
    size_capped: bool = False
    original_shares: int = 0


@dataclass
class AlphaShieldState:
    """Alpha Shield circuit breaker state."""
    is_triggered: bool = False
    triggered_at: Optional[datetime] = None
    triggered_drawdown: float = 0.0
    high_water_mark: float = 0.0
    current_equity: float = 0.0
    
    # Auto-reset settings
    auto_reset_enabled: bool = False
    reset_threshold: float = 0.5  # Reset when recovered 50% of drawdown


class RiskManager:
    """
    Risk management for the Velocity Engine.
    
    Handles position sizing, limit enforcement, and circuit breakers.
    """
    
    def __init__(
        self,
        base_capital: float = None,
        risk_per_trade: float = None,
        max_position_pct: float = None,
        max_positions: int = None,
        drawdown_limit: float = None,
        vix_filter: VixFilter = None
    ):
        """
        Initialize risk manager.
        
        Args:
            base_capital: Starting capital (uses config default).
            risk_per_trade: Risk per trade as decimal (uses config default).
            max_position_pct: Max position size as decimal (uses config default).
            max_positions: Maximum concurrent positions (uses config default).
            drawdown_limit: Alpha Shield threshold as decimal (uses config default).
            vix_filter: VIX filter instance for volatility adjustment.
        """
        self.base_capital = base_capital or BASE_CAPITAL
        self.risk_per_trade = risk_per_trade or RISK_PER_TRADE
        self.max_position_pct = max_position_pct or MAX_POSITION_SIZE_PCT
        self.max_positions = max_positions or MAX_POSITIONS
        self.drawdown_limit = drawdown_limit or ALPHA_SHIELD_DRAWDOWN
        
        self.vix_filter = vix_filter or VixFilter()
        
        # Equity tracking
        self._current_equity = self.base_capital
        self._high_water_mark = self.base_capital
        self._current_positions: List[Dict] = []
        
        # Alpha Shield state
        self.alpha_shield = AlphaShieldState(
            high_water_mark=self.base_capital,
            current_equity=self.base_capital
        )
        
        logger.info(
            f"RiskManager initialized - Capital: ${self.base_capital:,.2f}, "
            f"Risk/Trade: {self.risk_per_trade:.1%}, "
            f"Max Positions: {self.max_positions}, "
            f"Drawdown Limit: {self.drawdown_limit:.1%}"
        )
    
    # =========================================================================
    # Equity & Drawdown Tracking
    # =========================================================================
    
    def update_equity(self, equity: float) -> None:
        """
        Update current equity and high water mark.
        
        Args:
            equity: Current account equity.
        """
        self._current_equity = equity
        self.alpha_shield.current_equity = equity
        
        if equity > self._high_water_mark:
            self._high_water_mark = equity
            self.alpha_shield.high_water_mark = equity
            logger.debug(f"New high water mark: ${equity:,.2f}")
        
        # Check Alpha Shield
        self._check_alpha_shield()
    
    def get_drawdown(self) -> tuple[float, float]:
        """
        Get current drawdown.
        
        Returns:
            Tuple of (absolute_drawdown, percentage_drawdown).
        """
        if self._high_water_mark <= 0:
            return 0.0, 0.0
        
        drawdown_abs = self._high_water_mark - self._current_equity
        drawdown_pct = drawdown_abs / self._high_water_mark
        
        return drawdown_abs, drawdown_pct
    
    def _check_alpha_shield(self) -> None:
        """Check and update Alpha Shield status."""
        _, drawdown_pct = self.get_drawdown()
        
        if not self.alpha_shield.is_triggered:
            # Check if should trigger
            if drawdown_pct >= self.drawdown_limit:
                self.alpha_shield.is_triggered = True
                self.alpha_shield.triggered_at = datetime.now(timezone.utc)
                self.alpha_shield.triggered_drawdown = drawdown_pct
                
                logger.warning(
                    f"⚠️ ALPHA SHIELD TRIGGERED - "
                    f"Drawdown: {drawdown_pct:.2%} >= {self.drawdown_limit:.2%}"
                )
        else:
            # Check for auto-reset
            if self.alpha_shield.auto_reset_enabled:
                recovery_needed = self.alpha_shield.triggered_drawdown * self.alpha_shield.reset_threshold
                
                if drawdown_pct <= (self.alpha_shield.triggered_drawdown - recovery_needed):
                    self.reset_alpha_shield()
                    logger.info("Alpha Shield auto-reset after recovery")
    
    def reset_alpha_shield(self) -> None:
        """Manually reset Alpha Shield."""
        self.alpha_shield.is_triggered = False
        self.alpha_shield.triggered_at = None
        self.alpha_shield.triggered_drawdown = 0.0
        logger.info("Alpha Shield reset")
    
    def is_alpha_shield_triggered(self) -> bool:
        """Check if Alpha Shield is triggered."""
        return self.alpha_shield.is_triggered
    
    # =========================================================================
    # Position Tracking
    # =========================================================================
    
    def set_positions(self, positions: List[Dict]) -> None:
        """
        Update current positions.
        
        Args:
            positions: List of position dictionaries with 'symbol', 'value'.
        """
        self._current_positions = positions
    
    def get_position_count(self) -> int:
        """Get current position count."""
        return len(self._current_positions)
    
    def get_total_exposure(self) -> float:
        """Get total position value."""
        return sum(p.get('value', 0) for p in self._current_positions)
    
    def has_position(self, symbol: str) -> bool:
        """Check if we have a position in symbol."""
        return any(p.get('symbol') == symbol for p in self._current_positions)
    
    # =========================================================================
    # Position Sizing
    # =========================================================================
    
    def calculate_position_size(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        equity: float = None,
        apply_vix_adjustment: bool = True
    ) -> PositionSizeResult:
        """
        Calculate position size with all risk checks.
        
        Args:
            symbol: Stock symbol.
            entry_price: Intended entry price.
            stop_loss: Stop loss price.
            equity: Account equity (uses tracked equity if not provided).
            apply_vix_adjustment: Apply VIX-based size reduction.
            
        Returns:
            PositionSizeResult with shares and validation status.
        """
        equity = equity or self._current_equity
        
        # Check Alpha Shield
        if self.is_alpha_shield_triggered():
            return PositionSizeResult(
                shares=0,
                position_value=0,
                risk_amount=0,
                risk_per_share=0,
                is_valid=False,
                rejection_reason="Alpha Shield triggered - trading blocked"
            )
        
        # Check position limit
        if self.get_position_count() >= self.max_positions:
            return PositionSizeResult(
                shares=0,
                position_value=0,
                risk_amount=0,
                risk_per_share=0,
                is_valid=False,
                rejection_reason=f"Max positions ({self.max_positions}) reached"
            )
        
        # Check if already in position
        if self.has_position(symbol):
            return PositionSizeResult(
                shares=0,
                position_value=0,
                risk_amount=0,
                risk_per_share=0,
                is_valid=False,
                rejection_reason=f"Already have position in {symbol}"
            )
        
        # Calculate risk per share
        risk_per_share = entry_price - stop_loss
        
        if risk_per_share <= 0:
            return PositionSizeResult(
                shares=0,
                position_value=0,
                risk_amount=0,
                risk_per_share=0,
                is_valid=False,
                rejection_reason="Invalid stop loss (must be below entry)"
            )
        
        # Base risk amount
        risk_amount = equity * self.risk_per_trade
        
        # Apply VIX adjustment
        vix_multiplier = 1.0
        vix_adjusted = False
        
        if apply_vix_adjustment:
            vix_multiplier = self.vix_filter.get_position_multiplier()
            
            if vix_multiplier < 1.0:
                vix_adjusted = True
                risk_amount *= vix_multiplier
                logger.debug(f"VIX adjustment applied: {vix_multiplier:.0%}")
            
            if vix_multiplier == 0:
                return PositionSizeResult(
                    shares=0,
                    position_value=0,
                    risk_amount=0,
                    risk_per_share=risk_per_share,
                    is_valid=False,
                    rejection_reason="VIX too high - trading blocked"
                )
        
        # Calculate shares
        shares = int(risk_amount / risk_per_share)
        original_shares = shares
        
        # Apply max position size cap
        max_position_value = equity * self.max_position_pct
        max_shares = int(max_position_value / entry_price)
        
        size_capped = False
        if shares > max_shares:
            shares = max_shares
            size_capped = True
            logger.debug(f"Position size capped: {original_shares} -> {shares}")
        
        # Final position value
        position_value = shares * entry_price
        
        if shares <= 0:
            return PositionSizeResult(
                shares=0,
                position_value=0,
                risk_amount=risk_amount,
                risk_per_share=risk_per_share,
                is_valid=False,
                rejection_reason="Calculated position size is 0"
            )
        
        return PositionSizeResult(
            shares=shares,
            position_value=position_value,
            risk_amount=risk_amount,
            risk_per_share=risk_per_share,
            is_valid=True,
            vix_adjusted=vix_adjusted,
            size_capped=size_capped,
            original_shares=original_shares
        )
    
    # =========================================================================
    # Risk Status
    # =========================================================================
    
    def get_risk_limits(self, equity: float = None) -> RiskLimits:
        """
        Get current risk limits and usage.
        
        Args:
            equity: Account equity (uses tracked equity if not provided).
            
        Returns:
            RiskLimits with all current values.
        """
        equity = equity or self._current_equity
        
        position_count = self.get_position_count()
        total_exposure = self.get_total_exposure()
        drawdown_abs, drawdown_pct = self.get_drawdown()
        
        vix_multiplier = self.vix_filter.get_position_multiplier()
        
        # Determine status
        if self.is_alpha_shield_triggered():
            status = RiskStatus.BLOCKED
            reason = "Alpha Shield triggered"
        elif vix_multiplier == 0:
            status = RiskStatus.BLOCKED
            reason = "VIX extreme - trading blocked"
        elif drawdown_pct >= self.drawdown_limit * 0.8:
            status = RiskStatus.RESTRICTED
            reason = f"Approaching drawdown limit ({drawdown_pct:.1%})"
        elif vix_multiplier < 1.0 or position_count >= self.max_positions - 1:
            status = RiskStatus.CAUTION
            reasons = []
            if vix_multiplier < 1.0:
                reasons.append(f"VIX elevated ({vix_multiplier:.0%} size)")
            if position_count >= self.max_positions - 1:
                reasons.append("Near position limit")
            reason = ", ".join(reasons)
        else:
            status = RiskStatus.NORMAL
            reason = "All systems normal"
        
        return RiskLimits(
            max_positions=self.max_positions,
            current_positions=position_count,
            positions_available=max(0, self.max_positions - position_count),
            max_position_value=equity * self.max_position_pct,
            current_exposure=total_exposure,
            exposure_pct=total_exposure / equity if equity > 0 else 0,
            drawdown_limit=self.drawdown_limit,
            current_drawdown=drawdown_abs,
            drawdown_pct=drawdown_pct,
            risk_per_trade=self.risk_per_trade,
            vix_multiplier=vix_multiplier,
            adjusted_risk=self.risk_per_trade * vix_multiplier,
            status=status,
            status_reason=reason
        )
    
    def allows_new_trade(self) -> tuple[bool, str]:
        """
        Quick check if new trades are allowed.
        
        Returns:
            Tuple of (allowed, reason).
        """
        limits = self.get_risk_limits()
        
        if limits.status == RiskStatus.BLOCKED:
            return False, limits.status_reason
        
        if limits.positions_available <= 0:
            return False, "Maximum positions reached"
        
        return True, "Trade allowed"
    
    def get_status_summary(self) -> Dict:
        """Get risk status summary for dashboard."""
        limits = self.get_risk_limits()
        
        return {
            "status": limits.status.value,
            "reason": limits.status_reason,
            "alpha_shield_triggered": self.is_alpha_shield_triggered(),
            "positions": f"{limits.current_positions}/{limits.max_positions}",
            "drawdown": f"{limits.drawdown_pct:.1%}",
            "drawdown_limit": f"{limits.drawdown_limit:.1%}",
            "vix_multiplier": f"{limits.vix_multiplier:.0%}",
            "equity": f"${self._current_equity:,.2f}",
            "high_water_mark": f"${self._high_water_mark:,.2f}"
        }
