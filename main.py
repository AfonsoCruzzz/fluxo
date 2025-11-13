import asyncio
import inspect
import spade
from spade.xmpp_client import XMPPClient
from agents.traffic_agent_universal import UniversalTrafficAgent
from agents.monitor_agent import TrafficMonitorAgent
from setup_sumo import criar_arquivos_sumo


def _garantir_compatibilidade_slixmpp():
    """Adaptar chamada connect() para Slixmpp>=1.8, que usa apenas 'address'."""
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
    )
    
    traffic_monitor = TrafficMonitorAgent(
        "monitor@localhost", 
        "senha",
        controller_jid="traffic_controller@localhost"
    )
    
    # Iniciar agentes
    await traffic_controller.start()
    await traffic_monitor.start()
    
    print("✅ Sistema iniciado. Pressione Ctrl+C para parar.")
    
    try:
        # Manter sistema rodando
        await asyncio.Future()
    except KeyboardInterrupt:
        print("🛑 Parando sistema...")
        await traffic_controller.stop()
        await traffic_monitor.stop()

if __name__ == "__main__":
    spade.run(main())
