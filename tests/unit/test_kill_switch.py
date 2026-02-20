from __future__ import annotations

import pytest

from src.core.exceptions import KillSwitchError
from src.services.risk.kill_switch import KillSwitch


@pytest.mark.asyncio
async def test_kill_switch_trip_and_reset() -> None:
    kill_switch = KillSwitch()

    kill_switch.assert_healthy()
    await kill_switch.trip("test reason")

    assert kill_switch.is_tripped is True
    assert kill_switch.reason == "test reason"

    with pytest.raises(KillSwitchError):
        kill_switch.assert_healthy()

    await kill_switch.reset()
    assert kill_switch.is_tripped is False
