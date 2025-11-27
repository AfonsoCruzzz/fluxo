import asyncio
from typing import Optional

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour

from sumo_controller import TraCIController


class VehicleAgent(Agent):
    """Agente que monitora um veículo específico no SUMO."""

    def __init__(
        self,
        jid: str,
        password: str,
        vehicle_id: str,
        controller: TraCIController,
        poll_interval: float = 1.0,
    ):
        super().__init__(jid, password)
        self.vehicle_id = vehicle_id
        self.controller = controller
        self.poll_interval = poll_interval

    async def setup(self) -> None:
        self.add_behaviour(self._MonitorVehicle())

    class _MonitorVehicle(CyclicBehaviour):
        async def run(self) -> None:
            vid = self.agent.vehicle_id
            try:
                async with self.agent.controller.traci_guard() as traci_conn:
                    if vid not in traci_conn.vehicle.getIDList():
                        await self.agent.stop()
                        return

                    # Coletar métricas básicas (poderiam ser enviadas a outros agentes).
                    _ = traci_conn.vehicle.getSpeed(vid)
                    _ = traci_conn.vehicle.getWaitingTime(vid)
                    _ = traci_conn.vehicle.getLaneID(vid)
            except Exception:
                # Se falhar a leitura, tenta novamente no próximo ciclo.
                pass

            await asyncio.sleep(self.agent.poll_interval)
