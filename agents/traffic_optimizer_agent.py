import json
from typing import Dict, Optional, Tuple

from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template


class TrafficOptimizerAgent(Agent):
    """Central arbiter: receives demand requests from head agents and grants one at a time."""

    def __init__(self, jid: str, password: str):
        super().__init__(jid, password)
        self.pending: Dict[Tuple[str, int], float] = {}

    async def setup(self) -> None:
        template = Template()
        template.set_metadata("protocol", "fipa-request")
        template.set_metadata("ontology", "tl-head")
        self.add_behaviour(self._Arbitrate(), template)

    class _Arbitrate(CyclicBehaviour):
        async def run(self) -> None:
            # Consume all messages currently in the inbox
            while self.messages:
                msg = await self.receive(timeout=0)
                if msg is None:
                    break
                if msg.get_metadata("protocol") != "fipa-request":
                    continue
                if msg.get_metadata("performative") != "request":
                    continue
                if msg.get_metadata("ontology") != "tl-head":
                    continue
                try:
                    data = json.loads(msg.body)
                except Exception:
                    continue
                if data.get("action") != "grant_green":
                    continue
                tl_id = data.get("tl_id")
                link_group_index = data.get("link_group_index")
                waiting = float(data.get("waiting", 0.0))
                if tl_id is None or link_group_index is None:
                    continue
                self.agent.pending[(tl_id, int(link_group_index))] = waiting

                # AGREE reply
                agree = msg.make_reply()
                agree.set_metadata("performative", "agree")
                agree.set_metadata("protocol", "fipa-request")
                agree.set_metadata("ontology", "tl-head")
                agree.body = json.dumps(
                    {"result": "accepted", "tl_id": tl_id, "link_group_index": link_group_index}
                )
                await self.send(agree)

            if not self.agent.pending:
                await self.sleep(0.2)
                return

            # Pick the head with the highest waiting metric
            (tl_id, link_group_index), waiting = max(self.agent.pending.items(), key=lambda item: item[1])
            self.agent.pending.clear()

            grant = Message(to=self.agent._build_head_jid(tl_id, link_group_index))
            grant.set_metadata("performative", "inform")
            grant.set_metadata("protocol", "fipa-request")
            grant.set_metadata("ontology", "tl-head")
            grant.body = json.dumps(
                {"result": "grant", "tl_id": tl_id, "link_group_index": link_group_index, "waiting": waiting}
            )
            await self.send(grant)
            await self.sleep(0.2)

    def _build_head_jid(self, tl_id: str, link_group_index: int) -> str:
        # Expect heads to use the same domain as this agent
        domain = self.jid.split("@", 1)[1]
        return f"tl_{tl_id}_g{link_group_index}@{domain}"
