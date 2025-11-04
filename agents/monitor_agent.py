import asyncio
import spade
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message

class TrafficMonitorAgent(Agent):
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
                # Poderia enviar comando para ajustar semáforos, etc.

    async def setup(self):
        print("📊 Iniciando Agente Monitor de Tráfego...")
        self.add_behaviour(self.MonitorBehaviour())
