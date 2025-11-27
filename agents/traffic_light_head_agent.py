import asyncio
from typing import List

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour

from sumo_controller import TraCIController


class TrafficLightHeadAgent(Agent):
    """Agent controlling a single signal head (link index) of a TLS."""

    def __init__(
        self,
        jid: str,
        password: str,
        traffic_light_id: str,
        link_index: int,
        link_count: int,
        controller: TraCIController,
        green_duration: float = 6.0,
        pause_duration: float = 2.0,
    ):
        super().__init__(jid, password)
        self.traffic_light_id = traffic_light_id
        self.link_index = link_index
        self.link_count = link_count
        self.controller = controller
        self.green_duration = green_duration
        self.pause_duration = pause_duration

    async def setup(self) -> None:
        self.add_behaviour(self._CycleHead())

    class _CycleHead(CyclicBehaviour):
        async def run(self) -> None:
            tl_id = self.agent.traffic_light_id
            link_index = self.agent.link_index
            link_count = self.agent.link_count

            try:
                async with self.agent.controller.traci_guard() as traci_conn:
                    # Build a state string with all red except this head as green.
                    state_chars: List[str] = ["r"] * link_count
                    state_chars[link_index] = "G"
                    traci_conn.trafficlight.setRedYellowGreenState(tl_id, "".join(state_chars))
            except Exception:
                # Ignore transient errors and try again next cycle.
                pass

            await asyncio.sleep(self.agent.green_duration)

            try:
                async with self.agent.controller.traci_guard() as traci_conn:
                    state_chars = ["r"] * link_count
                    traci_conn.trafficlight.setRedYellowGreenState(tl_id, "".join(state_chars))
            except Exception:
                pass

            await asyncio.sleep(self.agent.pause_duration)
