import asyncio
import json
from typing import List, Optional

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template

from sumo_controller import TraCIController


class TrafficLightHeadAgent(Agent):
    """Agent controlling a single signal head (link index) of a TLS."""

    def __init__(
        self,
        jid: str,
        password: str,
        traffic_light_id: str,
        link_group_index: int,
        link_indices: List[int],
        link_count: int,
        controller: TraCIController,
        lane_id: str,
        optimizer_jid: str,
        green_duration: float = 6.0,
        pause_duration: float = 2.0,
        ):
        super().__init__(jid, password)
        self.traffic_light_id = traffic_light_id
        self.link_group_index = link_group_index
        self.link_indices = link_indices
        self.link_count = link_count
        self.controller = controller
        self.lane_id = lane_id
        self.optimizer_jid = optimizer_jid
        self.green_duration = green_duration
        self.pause_duration = pause_duration

    async def setup(self) -> None:
        template = Template()
        template.set_metadata("protocol", "fipa-request")
        template.set_metadata("ontology", "tl-head")
        self.add_behaviour(self._CycleHead(), template)

    class _CycleHead(CyclicBehaviour):
        async def run(self) -> None:
            tl_id = self.agent.traffic_light_id
            link_indices = self.agent.link_indices
            link_group_index = self.agent.link_group_index
            link_count = self.agent.link_count

            # Measure demand on this lane.
            waiting_metric = 0.0
            try:
                async with self.agent.controller.traci_guard() as traci_conn:
                    waiting_metric = float(traci_conn.lane.getLastStepHaltingNumber(self.agent.lane_id))
            except Exception:
                waiting_metric = 0.0

            # Ask optimizer for permission to turn green.
            try:
                msg = Message(to=self.agent.optimizer_jid)
                msg.set_metadata("performative", "request")
                msg.set_metadata("protocol", "fipa-request")
                msg.set_metadata("ontology", "tl-head")
                msg.body = json.dumps(
                    {
                        "action": "grant_green",
                        "tl_id": tl_id,
                        "link_group_index": link_group_index,
                        "waiting": waiting_metric,
                    }
                )
                await self.send(msg)
            except Exception:
                await asyncio.sleep(self.agent.pause_duration)
                return

            # Wait for grant (non-blocking loop with timeout)
            grant: Optional[Message] = None
            remaining = self.agent.pause_duration
            while remaining > 0 and grant is None:
                candidate = await self.receive(timeout=min(0.2, remaining))
                remaining -= 0.2
                if candidate is None:
                    continue
                if candidate.get_metadata("protocol") != "fipa-request":
                    continue
                if candidate.get_metadata("ontology") != "tl-head":
                    continue
                perf = candidate.get_metadata("performative")
                if perf not in {"agree", "inform"}:
                    continue
                try:
                    data = json.loads(candidate.body)
                except Exception:
                    continue
                if (
                    data.get("result") == "grant"
                    and data.get("tl_id") == tl_id
                    and int(data.get("link_group_index", -1)) == link_group_index
                ):
                    grant = candidate
                    break

            if grant is None:
                await asyncio.sleep(self.agent.pause_duration)
                return

            # Apply green only for this head; others red.
            try:
                async with self.agent.controller.traci_guard() as traci_conn:
                    state_chars: List[str] = ["r"] * link_count
                    for idx in link_indices:
                        if 0 <= idx < link_count:
                            state_chars[idx] = "G"
                    traci_conn.trafficlight.setRedYellowGreenState(tl_id, "".join(state_chars))
            except Exception:
                await asyncio.sleep(self.agent.pause_duration)
                return

            await asyncio.sleep(self.agent.green_duration)

            try:
                async with self.agent.controller.traci_guard() as traci_conn:
                    state_chars = ["r"] * link_count
                    traci_conn.trafficlight.setRedYellowGreenState(tl_id, "".join(state_chars))
            except Exception:
                pass

            await asyncio.sleep(self.agent.pause_duration)
