import asyncio
from contextlib import asynccontextmanager
from typing import Iterable

import traci


class TraCIController:
    """Thin wrapper over TraCI with an asyncio lock to serialize access."""

    def __init__(self, sumo_binary: str, config_path: str, step_length: float = 1.0):
        self.sumo_binary = sumo_binary
        self.config_path = config_path
        self.step_length = step_length
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start SUMO/TraCI."""
        cmd = [
            self.sumo_binary,
            "-c",
            self.config_path,
            "--start",
            "--quit-on-end",
            "--step-length",
            str(self.step_length),
        ]
        # TraCI runs in-process; this call blocks until the TraCI socket is ready.
        traci.start(cmd)

    @asynccontextmanager
    async def traci_guard(self):
        """Serialize TraCI access across agents."""
        async with self._lock:
            yield traci

    async def simulation_step(self) -> None:
        async with self._lock:
            traci.simulationStep()

    def tls_ids(self) -> Iterable[str]:
        return traci.trafficlight.getIDList()

    def remaining_vehicles(self) -> int:
        return traci.simulation.getMinExpectedNumber()

    async def close(self) -> None:
        async with self._lock:
            if traci.isLoaded():
                traci.close(False)
