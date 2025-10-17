import asyncio
import logging
from spade import agent, behaviour
from spade.message import Message  # <-- new import

logging.basicConfig(level=logging.INFO)


class PingAgent(agent.Agent):
    class PingBehaviour(behaviour.CyclicBehaviour):
        async def on_start(self):
            print(f"[{self.agent.name}] PingBehaviour started.")
            await asyncio.sleep(1)  # give the other agent time to start

        async def run(self):
            # use Message class instead of make_message
            msg = Message(to="agent2@localhost")
            msg.body = "ping"
            await self.send(msg)
            print(f"[{self.agent.name}] Sent: ping")
            await asyncio.sleep(2)

    async def setup(self):
        print(f"[{self.name}] Agent starting...")
        self.add_behaviour(self.PingBehaviour())


class PongAgent(agent.Agent):
    class PongBehaviour(behaviour.CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=5)
            if msg:
                print(f"[{self.agent.name}] Received: {msg.body}")
                if msg.body.lower() == "ping":
                    reply = Message(to=str(msg.sender))
                    reply.body = "pong"
                    await self.send(reply)
                    print(f"[{self.agent.name}] Replied with: pong")
            await asyncio.sleep(1)

    async def setup(self):
        print(f"[{self.name}] Agent starting...")
        self.add_behaviour(self.PongBehaviour())


async def main():
    pong_agent = PongAgent("agent2@localhost", "senha")
    await pong_agent.start(auto_register=True)

    ping_agent = PingAgent("agent1@localhost", "senha")
    await ping_agent.start(auto_register=True)

    await asyncio.sleep(15)

    await ping_agent.stop()
    await pong_agent.stop()
    print("Agents stopped.")


if __name__ == "__main__":
    asyncio.run(main())