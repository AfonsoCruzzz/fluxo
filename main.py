import asyncio
import spade
from agents.traffic_agent_universal import UniversalTrafficAgent
from agents.monitor_agent import TrafficMonitorAgent
from setup_sumo import criar_arquivos_sumo

async def main():
    # Escolher mapa padrão (interseção clássica)
    sumo_config = criar_arquivos_sumo("cross.sumocfg")
    
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
        "senha"
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
