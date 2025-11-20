import sys
import time
from typing import Optional

from agents import TrafficLightAgent, VehicleAgent
from setup_sumo import DEFAULT_SUMO_CONFIG, configurar_sumo, criar_arquivos_sumo


def run_simulation(
    config_name: str = DEFAULT_SUMO_CONFIG,
    max_steps: int = 600,
    spawn_interval: int = 20,
    use_gui: bool = True,
    sleep_per_step: Optional[float] = None,
) -> None:
    """
    Launch SUMO and run two agent types:
      - VehicleAgent spawns traffic on predefined routes.
      - One TrafficLightAgent per intersection cycles through its own phases.
    """
    if not configurar_sumo():
        sys.exit("❌ SUMO não encontrado. Defina a variável de ambiente SUMO_HOME ou ajuste o setup.")

    try:
        from sumolib import checkBinary
        import traci
    except ImportError as exc:
        sys.exit(f"❌ Dependências do SUMO não disponíveis: {exc}")

    config_path = criar_arquivos_sumo(config_name)
    binary = checkBinary("sumo-gui" if use_gui else "sumo")

    cmd = [
        binary,
        "-c",
        config_path,
        "--start",
        "--quit-on-end",
        "--step-length",
        "1.0",
        "--ignore-route-errors",
        "true",
        "--time-to-teleport",
        "-1",
    ]

    print(f"🚀 Iniciando SUMO {'GUI' if use_gui else 'CLI'} com configuração '{config_name}'...")
    traci.start(cmd)

    traffic_light_ids = traci.trafficlight.getIDList()
    traffic_light_agents = [TrafficLightAgent(tl_id) for tl_id in traffic_light_ids]
    for agent in traffic_light_agents:
        agent.initialize()

    vehicle_agent = VehicleAgent(spawn_interval=spawn_interval)

    print(f"🚦 Semáforos controlados: {', '.join(traffic_light_ids) if traffic_light_ids else 'nenhum encontrado'}")
    print(f"🚗 Gerador de veículos ativo (intervalo: {spawn_interval} passos).")

    step_index = 0
    if sleep_per_step is None:
        sleep_per_step = 0.2 if use_gui else 0.0

    try:
        while step_index < max_steps:
            for tl_agent in traffic_light_agents:
                tl_agent.step()
            vehicle_agent.step(step_index)

            traci.simulationStep()
            step_index += 1

            if sleep_per_step > 0:
                time.sleep(sleep_per_step)
    except KeyboardInterrupt:
        print("🛑 Encerrando simulação...")
    finally:
        traci.close(False)
        print("✅ SUMO encerrado.")


if __name__ == "__main__":
    run_simulation()
