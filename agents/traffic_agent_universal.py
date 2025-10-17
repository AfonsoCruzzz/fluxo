import asyncio
import spade
from spade.agent import Agent
from spade.behaviour import PeriodicBehaviour
import os
import sys
import subprocess

# Define current_dir as the directory of the current script
current_dir = os.path.dirname(os.path.abspath(__file__))

# Configurar SUMO primeiro
from setup_sumo import configurar_sumo
SUMO_AVAILABLE = configurar_sumo()

if SUMO_AVAILABLE:
    try:
        import traci
        TRACI_AVAILABLE = True
    except ImportError:
        TRACI_AVAILABLE = False
else:
    TRACI_AVAILABLE = False

class UniversalTrafficAgent(Agent):
    def __init__(self, jid, password, sumo_config=os.path.join(current_dir, "sumo_files", "simple.sumocfg")):
        super().__init__(jid, password)
        self.sumo_config = sumo_config
        self.simulation_process = None
        
    async def setup(self):
        print("🚦 Agente de Tráfego Universal Iniciado")
        print(f"📊 SUMO disponível: {SUMO_AVAILABLE}")
        print(f"📊 TRACI disponível: {TRACI_AVAILABLE}")
        
        if TRACI_AVAILABLE and self.sumo_config:
            await self.start_simulation()
            self.add_behaviour(self.RealTrafficBehaviour(period=1.0))
        else:
            print("🔶 Executando em modo simulado")
            self.add_behaviour(self.SimulatedTrafficBehaviour(period=2.0))
    
    class RealTrafficBehaviour(PeriodicBehaviour):
        def __init__(self, period):
            super().__init__(period)
            self.spawned = set()
            self.depart_times = [1, 5, 10, 15]  # segundos de partida para cada veículo extra

        async def run(self):
            try:
                traci.simulationStep()
                sim_time = traci.simulation.getTime()

                # Cria veículos extras em tempos diferentes
                for idx, depart in enumerate(self.depart_times):
                    vehID = f"extra_{idx}"
                    if sim_time >= depart and vehID not in self.spawned:
                        try:
                            traci.vehicle.add(
                                vehID=vehID,
                                routeID="",
                                typeID="DEFAULT_VEHTYPE",
                                depart=sim_time,
                                departPos="base",
                                departSpeed="max",
                                departLane="best"
                            )
                            traci.vehicle.setRoute(vehID, ["E0", "E3", "E6", "E7"])
                            print(f"🚗 Veículo {vehID} criado em t={sim_time:.1f}")
                        except traci.TraCIException as e:
                            print(f"❌ Erro ao criar {vehID}: {e}")
                        self.spawned.add(vehID)

                # Mostrar até 5 veículos na simulação
                vehicles = traci.vehicle.getIDList()
                if vehicles:
                    for vehID in vehicles[:5]:
                        pos = traci.vehicle.getPosition(vehID)
                        speed = traci.vehicle.getSpeed(vehID)
                        print(f"🚗 {vehID}: Pos={pos}, Vel={speed:.1f}m/s")
                else:
                    print("🛣️  Estrada vazia...")

            except Exception as e:
                print(f"❌ Erro na simulação: {e}")
    
    class SimulatedTrafficBehaviour(PeriodicBehaviour):
        def __init__(self, period):
            super().__init__(period)
            self.step = 0
            
        async def run(self):
            self.step += 1
            vehicles = [
                {"id": "car1", "pos": (100 + self.step * 10, 50), "speed": 8.5},
                {"id": "car2", "pos": (200 - self.step * 8, 50), "speed": 7.2},
                {"id": "truck1", "pos": (50 + self.step * 5, 50), "speed": 5.0},
            ]
            
            for vehicle in vehicles:
                print(f"🚗 {vehicle['id']}: Pos={vehicle['pos']}, Vel={vehicle['speed']}m/s")
            
            print(f"📊 Passo de simulação: {self.step}")
    
    async def start_simulation(self):
        """Iniciar simulação SUMO de forma robusta"""
        if not TRACI_AVAILABLE:
            return
            
        try:
            # Encontrar sumo de qualquer maneira
            sumo_binary = self.find_sumo_binary()
            if not sumo_binary:
                print("❌ Não foi possível encontrar o executável SUMO")
                return
                
            cmd = [
                sumo_binary,
                "-c", self.sumo_config,
                "--start",
                "--step-length", "1.0",
            ]
            
            print(f"🚀 Iniciando SUMO: {' '.join(cmd)}")
            traci.start(cmd)
            print("✅ Simulação SUMO iniciada!")
            
        except Exception as e:
            print(f"❌ Erro ao iniciar SUMO: {e}")
    
    def find_sumo_binary(self):
        """Encontrar executável SUMO de forma robusta"""
        binaries = ["sumo-gui", "sumo", "sumoD", "sumo-guiD"]
        
        for binary in binaries:
            try:
                result = subprocess.run(["which", binary], capture_output=True, text=True)
                if result.returncode == 0:
                    return result.stdout.strip()
            except:
                continue
        
        # Tentar caminhos absolutos comuns
        common_paths = [
            "/usr/bin/sumo",
            "/usr/local/bin/sumo",
            "/app/bin/sumo",  # Flatpak
            "/snap/bin/sumo",  # Snap
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
                
        return None
    
    async def on_stop(self):
        if TRACI_AVAILABLE:
            try:
                traci.close()
            except:
                pass

async def main():
    # Criar arquivos SUMO se não existirem
    from setup_sumo import criar_arquivos_sumo
    sumo_config = criar_arquivos_sumo()
    
    agent = UniversalTrafficAgent("traffic@localhost", "senha", sumo_config)
    await agent.start()
    
    print("✅ Sistema iniciado. Pressione Ctrl+C para parar.")
    await asyncio.Future()

if __name__ == "__main__":
    spade.run(main())