import argparse
import asyncio
import inspect
import os
import shutil
from typing import Dict, Optional

import spade
from spade.xmpp_client import XMPPClient

from agents.traffic_light_head_agent import TrafficLightHeadAgent
from agents.vehicle_agent import VehicleAgent
from setup_sumo import configurar_sumo, criar_arquivos_sumo
from sumo_controller import TraCIController


def _resolver_config(config_arg: str) -> str:
    """Return an absolute path to a SUMO config file."""
    if os.path.isabs(config_arg) or os.path.exists(config_arg):
        return os.path.abspath(config_arg)
    return criar_arquivos_sumo(config_arg)


def _encontrar_binario_sumo() -> Optional[str]:
    """Prefer sumo-gui and fall back to sumo if needed."""
    candidatos: list[str] = []

    # 1) PATH
    for nome in ("sumo-gui", "sumo"):
        caminho = shutil.which(nome)
        if caminho:
            return caminho
    candidatos.extend(filter(None, (shutil.which("sumo-gui"), shutil.which("sumo"))))

    # 2) Inferir do SUMO_HOME (pkg macOS coloca bin dois níveis acima de share/sumo)
    sumo_home = os.environ.get("SUMO_HOME")
    if sumo_home:
        bin_dir = os.path.normpath(os.path.join(sumo_home, "..", "..", "bin"))
        for nome in ("sumo-gui", "sumo"):
            caminho = os.path.join(bin_dir, nome)
            if os.path.isfile(caminho) and os.access(caminho, os.X_OK):
                return caminho

    return candidatos[0] if candidatos else None


def _garantir_compatibilidade_slixmpp():
    """Patch SPADE's XMPP client for newer slixmpp versions."""
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


async def main() -> int:
    parser = argparse.ArgumentParser(description="Executar SUMO com SPADE: um agente por veículo e por semáforo.")
    parser.add_argument("--config", default="simple.sumocfg", help="Arquivo .sumocfg a usar.")
    parser.add_argument("--domain", default="localhost", help="Domínio XMPP para os agentes (ex.: localhost).")
    parser.add_argument("--password", default="senha", help="Senha padrão para todos os agentes.")
    parser.add_argument("--step-length", type=float, default=1.0, help="Tamanho do passo da simulação (s).")
    parser.add_argument("--nogui", action="store_true", help="Usar sumo (CLI) ao invés de sumo-gui.")
    args = parser.parse_args()

    if not configurar_sumo():
        print("Defina SUMO_HOME para apontar para a instalação do SUMO e tente novamente.")
        return 1

    # Importar traci após SUMO_HOME configurado.
    import traci  # noqa: WPS433

    try:
        config_path = _resolver_config(args.config)
    except FileNotFoundError as exc:
        print(exc)
        return 1

    sumo_bin = _encontrar_binario_sumo()
    if args.nogui:
        cli_bin = shutil.which("sumo")
        if cli_bin:
            sumo_bin = cli_bin
    if not sumo_bin:
        print("sumo-gui ou sumo não encontrados no PATH.")
        return 1

    controller = TraCIController(sumo_bin, config_path, step_length=args.step_length)
    await controller.start()

    # Criar agentes por cabeça de semáforo (um por linkIndex controlado).
    async with controller.traci_guard() as traci_conn:
        tls_ids = list(traci_conn.trafficlight.getIDList())
        link_counts: Dict[str, int] = {}
        for tl_id in tls_ids:
            links = traci_conn.trafficlight.getControlledLinks(tl_id)
            link_counts[tl_id] = len(links)

    traffic_light_agents = []
    for tl_id in tls_ids:
        count = link_counts.get(tl_id, 0)
        for link_index in range(count):
            agent = TrafficLightHeadAgent(
                jid=f"tl_{tl_id}_l{link_index}@{args.domain}",
                password=args.password,
                traffic_light_id=tl_id,
                link_index=link_index,
                link_count=count,
                controller=controller,
            )
            await agent.start()
            traffic_light_agents.append(agent)

    vehicle_agents: Dict[str, VehicleAgent] = {}
    print(f"🚦 Iniciando {len(traffic_light_agents)} agentes de semáforo (por cabeça); aguardando veículos da simulação...")

    try:
        while True:
            # Avançar simulação
            await controller.simulation_step()

            async with controller.traci_guard() as traci_conn:
                departed = traci_conn.simulation.getDepartedIDList()
                arrived = traci_conn.simulation.getArrivedIDList()

            # Spawn agents for new vehicles
            for veh_id in departed:
                if veh_id in vehicle_agents:
                    continue
                agent = VehicleAgent(
                    jid=f"veh_{veh_id}@{args.domain}",
                    password=args.password,
                    vehicle_id=veh_id,
                    controller=controller,
                )
                await agent.start()
                vehicle_agents[veh_id] = agent

            # Clean up agents for arrived vehicles
            for veh_id in arrived:
                agent = vehicle_agents.pop(veh_id, None)
                if agent:
                    await agent.stop()

            if controller.remaining_vehicles() == 0 and not vehicle_agents:
                break

            await asyncio.sleep(args.step_length)

    finally:
        for agent in vehicle_agents.values():
            await agent.stop()
        for agent in traffic_light_agents:
            await agent.stop()
        await controller.close()

    print("✅ Simulação finalizada.")
    return 0


if __name__ == "__main__":
    spade.run(main())
