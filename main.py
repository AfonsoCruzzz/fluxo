import asyncio
import spade
import os
from agents.traffic_agent_universal import UniversalTrafficAgent
from agents.monitor_agent import TrafficMonitorAgent

async def main():
    # Configurar caminhos
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sumo_config = os.path.join(current_dir, "sumo_files", "simple.sumocfg")
    
    print("🚀 Iniciando Sistema de Tráfego Inteligente...")
    
    # Criar agentes
    traffic_controller = UniversalTrafficAgent(
        "traffic_controller@localhost", 
        "senha", 
        sumo_config
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