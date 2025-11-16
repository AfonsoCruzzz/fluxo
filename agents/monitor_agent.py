import asyncio
import spade
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.message import Message
from spade.template import Template

class TrafficMonitorAgent(Agent):
    def __init__(self, jid, password, controller_jid=None):
        super().__init__(jid, password)
        self.controller_jid = controller_jid
        self._emergency_patterns = ("ambulance", "ambu", "fire", "brigade", "police")
        self._flagged_emergencies = set()

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
                    if self.agent.should_raise_emergency(vehicle_id):
                        await self.notify_controller(vehicle_id, "emergency")
                    await self.analyze_traffic(vehicle_id, position, float(speed))
                elif msg.body.startswith("VEHICLE_WAIT"):
                    parts = msg.body.split("|")
                    if len(parts) >= 3:
                        vehicle_id = parts[1]
                        wait_time = parts[2]
                        print(f"⏱️ MONITOR: {vehicle_id} aguardando há {wait_time}s")
        
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

    class NotifyReadyBehaviour(OneShotBehaviour):
        async def run(self):
            controller = self.agent.controller_jid
            if not controller:
                return
            msg = Message(to=controller)
            msg.body = "AGENT_READY|monitor"
            try:
                await self.send(msg)
            except Exception as exc:
                print(f"⚠️ Monitor não conseguiu avisar controlador sobre prontidão: {exc}")

    async def setup(self):
        print("📊 Iniciando Agente Monitor de Tráfego...")
        template = Template()  # aceitar todas as mensagens recebidas
        self.add_behaviour(self.MonitorBehaviour(), template=template)
        self.add_behaviour(self.NotifyReadyBehaviour())

    def should_raise_emergency(self, vehicle_id):
        """Detectar veículos de emergência por convenção de identificação."""
        if not vehicle_id:
            return False
        if vehicle_id in self._flagged_emergencies:
            return False

        vehicle_lower = vehicle_id.lower()
        if any(pattern in vehicle_lower for pattern in self._emergency_patterns):
            self._flagged_emergencies.add(vehicle_id)
            print(f"🚨 MONITOR: {vehicle_id} identificado como veículo de emergência")
            return True
        return False
