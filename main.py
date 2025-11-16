import asyncio
import inspect
import spade
from spade.xmpp_client import XMPPClient
from agents.traffic_agent_universal import UniversalTrafficAgent
from agents.monitor_agent import TrafficMonitorAgent
from agents.vehicle_agent import VehicleAgent
from setup_sumo import criar_arquivos_sumo


def _garantir_compatibilidade_slixmpp():
    assinatura = inspect.signature(XMPPClient.connect)
    if "host" in assinatura.parameters:
        return

    original_connect = XMPPClient.connect

    def patched_connect(self, *args, **kwargs):
        host = kwargs.pop("host", None)
        port = kwargs.pop("port", None)
        if host is not None and "address" not in kwargs:
            if port is None:
                port = getattr(self, "xmpp_port", None) or getattr(self, "port", None) or 5222
            kwargs["address"] = (host, port)
        return original_connect(self, *args, **kwargs)

    XMPPClient.connect = patched_connect


_garantir_compatibilidade_slixmpp()

async def main():
    # Escolher mapa padrão (interseção clássica)
    sumo_config = criar_arquivos_sumo("simple.sumocfg")
    
    print("🚀 Iniciando Sistema de Tráfego Inteligente...")
    
    # Criar agentes
    traffic_controller = UniversalTrafficAgent(
        "traffic_controller@localhost",
        "senha",
        sumo_config,
        monitor_jid="monitor@localhost",
        vehicle_jid="vehicle@localhost",
    )
    
    traffic_monitor = TrafficMonitorAgent(
        "monitor@localhost", 
        "senha",
        controller_jid="traffic_controller@localhost"
    )

    if sumo_config:
        pattern_routes = []
        tracked = {"ambulance0", "ambulance1", "ambulance2"}
    else:
        pattern_routes = [
            {"id_prefix": "north", "start": (0, 220), "end": (0, -220), "spawn_interval": 5.5, "speed": 13.0},
            {"id_prefix": "south", "start": (0, -220), "end": (0, 220), "spawn_interval": 6.0, "speed": 12.5},
            {"id_prefix": "east", "start": (-220, 0), "end": (220, 0), "spawn_interval": 4.8, "speed": 13.5},
            {"id_prefix": "west", "start": (220, 0), "end": (-220, 0), "spawn_interval": 5.2, "speed": 12.0},
            {"id_prefix": "ambulance", "start": (-200, -40), "end": (200, -40), "spawn_interval": 45.0, "speed": 16.0, "vehicle_type": "ambulance"},
        ]
        tracked = set()
    
    vehicle_agent = VehicleAgent(
        "vehicle@localhost",
        "senha",
        controller_jid="traffic_controller@localhost",
        # tracked_vehicles={"ambulance0", "ambulance1", "ambulance2"},
        monitor_jid="monitor@localhost",
        tracked_vehicles=tracked,
        pattern_routes=pattern_routes,
        pattern_period=1.0,
    )
    
    # Iniciar agentes
    await traffic_controller.start()
    await traffic_monitor.start()
    await vehicle_agent.start()
    
    print("✅ Sistema iniciado. Pressione Ctrl+C para parar.")
    
    try:
        await asyncio.Future()
    except KeyboardInterrupt:
        print("🛑 Parando sistema...")
        await traffic_controller.stop()
        await traffic_monitor.stop()
        await vehicle_agent.stop()

if __name__ == "__main__":
    spade.run(main())
