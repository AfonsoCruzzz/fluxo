import asyncio
import spade
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

class TrafficMonitorAgent(Agent):
    def __init__(self, jid, password, controller_jid=None):
        super().__init__(jid, password)
        self.controller_jid = controller_jid

    class MonitorBehaviour(CyclicBehaviour):
        async def run(self):
            # Aguardar mensagens do controlador
            msg = await self.receive(timeout=10)
            if msg:
                if "VEHICLE_UPDATE" in msg.body:
                    parts = msg.body.split("|")
                    vehicle_id = parts[1]
                    position = parts[2]
                    speed = parts[3]
                    
                    print(f"📊 MONITOR: {vehicle_id} em {position} a {speed}m/s")
                    
                    # Tomar decisões baseadas nos dados
                    await self.analyze_traffic(vehicle_id, position, float(speed))
        
        async def analyze_traffic(self, vehicle_id, position, speed):
            """Analisar tráfego e tomar decisões"""
            if speed < 5:
                print(f"⚠️  ALERTA: {vehicle_id} está muito lento!")
                await self.notify_controller(vehicle_id, "lento")

        async def notify_controller(self, vehicle_id, status):
            controller = self.agent.controller_jid
            if not controller:
                return

            msg = Message(to=controller)
            msg.body = f"TRAFFIC_ALERT|{vehicle_id}|{status}"
            try:
                await self.send(msg)
                print(f"📨 MONITOR: alerta '{status}' enviado para controlador ({vehicle_id})")
            except Exception as exc:
                print(f"⚠️  Monitor não conseguiu notificar controlador: {exc}")

    async def setup(self):
        print("📊 Iniciando Agente Monitor de Tráfego...")
        self.add_behaviour(self.MonitorBehaviour())
