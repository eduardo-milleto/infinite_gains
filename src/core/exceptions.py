from __future__ import annotations


class InfiniteGainsError(RuntimeError):
    """Base error for all domain-specific failures."""


class KillSwitchError(InfiniteGainsError):
    """Raised when kill switch blocks trading actions."""


class RiskVetoError(InfiniteGainsError):
    """Raised when risk policy denies a trade."""


class MarketDiscoveryError(InfiniteGainsError):
    """Raised when market discovery or validation fails."""


class APIFailureError(InfiniteGainsError):
    """Raised when an upstream API call fails irrecoverably."""
