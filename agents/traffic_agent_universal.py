import asyncio
import spade
from spade.agent import Agent
from spade.behaviour import PeriodicBehaviour
from spade.message import Message
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
    def __init__(
        self,
        jid,
        password,
        sumo_config=os.path.join(current_dir, "sumo_files", "cross.sumocfg"),
        monitor_jid=None,
    ):
        super().__init__(jid, password)
        self.sumo_config = sumo_config
        self.simulation_process = None
        self.monitor_jid = monitor_jid
        
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
            self.depart_plan = []
            self.pass_threshold = None
            self.red_duration = 10  # segundos que permanecerá vermelho
            self.tl_data = {}
            self.tl_initialized = False
            self.lane_groups = {}
            self.group_metrics = {}
            self.min_main_green = 6.0
            self.max_main_green = 35.0
            self.min_left_green = 3.0
            self.max_left_green = 15.0
            self.clearance_duration = 2.0

        async def run(self):
            try:
                traci.simulationStep()
                sim_time = traci.simulation.getTime()

                if not self.tl_initialized:
                    self.initialize_traffic_lights()

                # Cria veículos extras em tempos diferentes
                for idx, (depart, route) in enumerate(self.depart_plan):
                    veh_id = f"extra_{idx}"
                    if sim_time >= depart and veh_id not in self.spawned:
                        try:
                            traci.vehicle.add(
                                vehID=veh_id,
                                routeID="",
                                typeID="DEFAULT_VEHTYPE",
                                depart=sim_time,
                                departPos="base",
                                departSpeed="max",
                                departLane="best"
                            )
                            traci.vehicle.setRoute(veh_id, list(route))
                            print(f"🚗 Veículo {veh_id} criado em t={sim_time:.1f} com rota {route}")
                        except traci.TraCIException as e:
                            print(f"❌ Erro ao criar {veh_id}: {e}")
                        self.spawned.add(veh_id)

                # Mostrar até 5 veículos na simulação
                vehicles = traci.vehicle.getIDList()
                if vehicles:
                    for vehID in vehicles[:5]:
                        pos = traci.vehicle.getPosition(vehID)
                        speed = traci.vehicle.getSpeed(vehID)
                        print(f"🚗 {vehID}: Pos={pos}, Vel={speed:.1f}m/s")
                        await self.agent.notify_monitor(vehID, pos, speed, self)
                else:
                    print("🛣️  Estrada vazia...")

                active_ids = set(traci.vehicle.getIDList())

                self._collect_group_metrics()
                self._update_pass_threshold()

                # Contar veículos que já cruzaram cada semáforo controlado
                for tl_id, data in self.tl_data.items():
                    self._cleanup_observed(data, active_ids)
                    newly_counted = 0

                    for edge in data["downstream_edges"]:
                        try:
                            edge_vehicles = traci.edge.getLastStepVehicleIDs(edge)
                        except traci.TraCIException:
                            continue
                        for veh_id in edge_vehicles:
                            if veh_id not in data["observed_after_light"]:
                                data["observed_after_light"].add(veh_id)
                                data["vehicles_since_switch"] += 1
                                newly_counted += 1

                    if newly_counted:
                        print(
                            f"🚦 Semáforo {tl_id}: {data['vehicles_since_switch']} veículo(s) desde a última troca"
                        )

                    self._adaptive_control(tl_id, data, sim_time)

                    if (
                        self.pass_threshold is not None
                        and not data["holding_red"]
                        and data["vehicles_since_switch"] >= self.pass_threshold
                    ):
                        self._force_red(tl_id, data, sim_time)

                    elif (
                        data["holding_red"]
                        and data["red_release_time"] is not None
                        and sim_time >= data["red_release_time"]
                    ):
                        self._restore_program(tl_id, data)

            except Exception as e:
                print(f"❌ Erro na simulação: {e}")

        def initialize_traffic_lights(self):
            self.tl_initialized = True
            ids = traci.trafficlight.getIDList()
            if not ids:
                print("⚠️ Nenhum semáforo disponível para controle.")
                return
            self._prepare_lane_groups()

            for tl_id in ids:
                try:
                    controlled_links = traci.trafficlight.getControlledLinks(tl_id)
                    downstream_edges = set()
                    for link_group in controlled_links:
                        if not link_group:
                            continue
                        # Cada grupo pode ter uma ou mais tuplas (incoming, outgoing, via)
                        for _, out_lane, _ in link_group:
                            if out_lane:
                                downstream_edges.add(out_lane.rsplit("_", 1)[0])

                    program_id = traci.trafficlight.getProgram(tl_id)
                    self.tl_data[tl_id] = {
                        "downstream_edges": downstream_edges,
                        "observed_after_light": set(),
                        "vehicles_since_switch": 0,
                        "holding_red": False,
                        "red_release_time": None,
                        "default_program": program_id,
                        "previous_state": None,
                        "previous_phase": None,
                        "phase_remaining": None,
                        "last_phase": None,
                        "last_phase_set_time": None,
                        "mode": "adaptive",
                    }
                    print(
                        f"ℹ️ Controlando semáforo {tl_id} com {len(downstream_edges)} via(s) monitorada(s)"
                    )
                except traci.TraCIException as e:
                    print(f"⚠️ Falha ao inicializar semáforo {tl_id}: {e}")

        def _cleanup_observed(self, data, active_ids):
            data["observed_after_light"].intersection_update(active_ids)

        def _prepare_lane_groups(self):
            try:
                from collections import defaultdict

                dynamic_groups = defaultdict(list)
                for tl_id in traci.trafficlight.getIDList():
                    controlled = traci.trafficlight.getControlledLinks(tl_id)
                    for link_group in controlled:
                        if not link_group:
                            continue
                        entry_lane = link_group[0][0]
                        exit_lane = link_group[0][1]
                        if "_left" in entry_lane:
                            dynamic_groups["LEFT"].append(entry_lane)
                        else:
                            dynamic_groups["MAIN"].append(entry_lane)
            except traci.TraCIException:
                dynamic_groups = {}

            if dynamic_groups:
                self.lane_groups = {
                    "EW_MAIN": [lane for lane in dynamic_groups["MAIN"] if lane.startswith("1") or lane.startswith("2")],
                    "EW_LEFT": [lane for lane in dynamic_groups["LEFT"] if lane.startswith("1") or lane.startswith("2")],
                    "NS_MAIN": [lane for lane in dynamic_groups["MAIN"] if lane.startswith("3") or lane.startswith("4")],
                    "NS_LEFT": [lane for lane in dynamic_groups["LEFT"] if lane.startswith("3") or lane.startswith("4")],
                }
                print(f"🛣️ Grupos de faixas detectados dinamicamente: {self.lane_groups}")
            else:
                self.lane_groups = {
                    "EW_MAIN": ["1si_0", "1si_1", "2si_0", "2si_1"],
                    "EW_LEFT": ["1si_2", "2si_2"],
                    "NS_MAIN": ["3si_0", "4si_0"],
                    "NS_LEFT": ["3si_1", "4si_1"],
                }
                print("🛣️ Usando grupos de faixas padrão configurados manualmente.")

        def _adaptive_control(self, tl_id, data, sim_time):
            try:
                phase = traci.trafficlight.getPhase(tl_id)
            except traci.TraCIException as e:
                print(f"⚠️ Falha ao ler fase do semáforo {tl_id}: {e}")
                return

            if data["mode"] != "adaptive":
                return

            if data["last_phase"] == phase:
                return

            data["last_phase"] = phase
            data["last_phase_set_time"] = sim_time

            try:
                if phase in (0,):
                    duration = self._compute_main_duration("EW_MAIN", "NS_MAIN")
                    traci.trafficlight.setPhaseDuration(tl_id, duration)
                elif phase in (4,):
                    duration = self._compute_main_duration("NS_MAIN", "EW_MAIN")
                    traci.trafficlight.setPhaseDuration(tl_id, duration)
                elif phase in (2,):
                    duration = self._compute_left_duration("EW_LEFT")
                    traci.trafficlight.setPhaseDuration(tl_id, duration)
                elif phase in (6,):
                    duration = self._compute_left_duration("NS_LEFT")
                    traci.trafficlight.setPhaseDuration(tl_id, duration)
                elif phase in (1, 5):
                    traci.trafficlight.setPhaseDuration(tl_id, 3.0)
                elif phase in (3, 7):
                    traci.trafficlight.setPhaseDuration(tl_id, self.clearance_duration)
            except traci.TraCIException as e:
                print(f"⚠️ Erro ao ajustar duração do semáforo {tl_id}: {e}")

        def _compute_main_duration(self, active_group, opposing_group):
            active_metrics = self.group_metrics.get(active_group, {})
            opposing_metrics = self.group_metrics.get(opposing_group, {})

            active_queue = active_metrics.get("queue", 0)
            active_wait = active_metrics.get("waiting", 0.0)
            active_speed = active_metrics.get("avg_speed", 0.0)
            opposing_queue = opposing_metrics.get("queue", 0)

            if active_queue == 0 and opposing_queue > 0:
                return 2.0

            demand_score = active_queue + (active_wait / 20.0)
            if active_speed < 4.0 and active_queue:
                demand_score += 2.0

            base = self.min_main_green + demand_score * 1.2
            if opposing_queue == 0:
                base = max(base, self.min_main_green + 2.0)

            duration = max(self.min_main_green, min(self.max_main_green, base))
            return float(duration)

        def _compute_left_duration(self, group):
            metrics = self.group_metrics.get(group, {})
            queue = metrics.get("queue", 0)
            wait = metrics.get("waiting", 0.0)

            if queue == 0:
                return 1.0

            demand_score = queue + (wait / 25.0)
            base = 4.0 + demand_score * 1.2
            duration = max(self.min_left_green, min(self.max_left_green, base))
            return float(duration)

        def _group_queue(self, group_name):
            lanes = self.lane_groups.get(group_name, [])
            total = 0
            for lane_id in lanes:
                try:
                    total += traci.lane.getLastStepHaltingNumber(lane_id)
                except traci.TraCIException:
                    continue
            return total

        def _collect_group_metrics(self):
            if not self.lane_groups:
                return

            metrics = {}
            for group, lanes in self.lane_groups.items():
                queue = 0
                waiting = 0.0
                vehicles = 0
                weighted_speed = 0.0

                for lane_id in lanes:
                    try:
                        queue += traci.lane.getLastStepHaltingNumber(lane_id)
                        waiting += traci.lane.getWaitingTime(lane_id)
                        lane_vehicles = traci.lane.getLastStepVehicleNumber(lane_id)
                        vehicles += lane_vehicles
                        if lane_vehicles:
                            weighted_speed += traci.lane.getLastStepMeanSpeed(lane_id) * lane_vehicles
                    except traci.TraCIException:
                        continue

                avg_speed = weighted_speed / vehicles if vehicles else 0.0
                metrics[group] = {
                    "queue": queue,
                    "waiting": waiting,
                    "avg_speed": avg_speed,
                    "vehicles": vehicles,
                }

            self.group_metrics = metrics

        def _update_pass_threshold(self):
            if not self.group_metrics:
                self.pass_threshold = None
                return

            total_queue = sum(data["queue"] for data in self.group_metrics.values())
            total_waiting = sum(data["waiting"] for data in self.group_metrics.values())
            total_vehicles = sum(data["vehicles"] for data in self.group_metrics.values())

            if total_vehicles == 0:
                self.pass_threshold = None
                return

            avg_wait = total_waiting / total_vehicles if total_vehicles else 0.0

            if total_queue >= 16 or avg_wait > 40:
                self.pass_threshold = 12
            elif total_queue >= 10 or avg_wait > 25:
                self.pass_threshold = 8
            elif total_queue >= 6 or avg_wait > 15:
                self.pass_threshold = 6
            else:
                self.pass_threshold = None

        def _force_red(self, tl_id, data, sim_time):
            try:
                try:
                    data["previous_phase"] = traci.trafficlight.getPhase(tl_id)
                    next_switch = traci.trafficlight.getNextSwitch(tl_id)
                    data["phase_remaining"] = max(0.0, next_switch - sim_time) if next_switch else None
                except traci.TraCIException:
                    data["previous_phase"] = None
                    data["phase_remaining"] = None

                current_state = traci.trafficlight.getRedYellowGreenState(tl_id)
                data["previous_state"] = current_state
                red_state = "r" * len(current_state)
                traci.trafficlight.setRedYellowGreenState(tl_id, red_state)
                data["holding_red"] = True
                data["red_release_time"] = sim_time + self.red_duration
                data["vehicles_since_switch"] = 0
                print(
                    (f"🔴 Semáforo {tl_id} em vermelho por {self.red_duration}s "
                     f"após {self.pass_threshold} veículos" if self.pass_threshold is not None else
                     f"🔴 Semáforo {tl_id} mantido em vermelho por {self.red_duration}s")
                )
            except traci.TraCIException as e:
                print(f"❌ Erro ao alterar semáforo {tl_id}: {e}")

        def _restore_program(self, tl_id, data):
            try:
                default_program = data.get("default_program")
                if default_program is not None:
                    traci.trafficlight.setProgram(tl_id, default_program)
                    if data.get("previous_phase") is not None:
                        traci.trafficlight.setPhase(tl_id, data["previous_phase"])
                        if data.get("phase_remaining"):
                            traci.trafficlight.setPhaseDuration(
                                tl_id, max(0.1, data["phase_remaining"])
                            )
                elif data.get("previous_state"):
                    traci.trafficlight.setRedYellowGreenState(tl_id, data["previous_state"])

                data["holding_red"] = False
                data["red_release_time"] = None
                data["previous_state"] = None
                data["previous_phase"] = None
                data["phase_remaining"] = None
                data["observed_after_light"].clear()
                print(f"🟢 Semáforo {tl_id} liberado para verde")
            except traci.TraCIException as e:
                print(f"❌ Erro ao liberar semáforo {tl_id}: {e}")
    
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
                {"id": "car3", "pos": (75, 120 - self.step * 6), "speed": 6.8},
                {"id": "car4", "pos": (140 - self.step * 4, 90), "speed": 7.9},
                {"id": "bus1", "pos": (30 + self.step * 3, 130), "speed": 4.5},
            ]
            
            for vehicle in vehicles:
                print(f"🚗 {vehicle['id']}: Pos={vehicle['pos']}, Vel={vehicle['speed']}m/s")
                await self.agent.notify_monitor(
                    vehicle["id"], vehicle["pos"], vehicle["speed"], self
                )
            
            print(f"📊 Passo de simulação: {self.step}")
    
    async def start_simulation(self):
        """Iniciar simulação SUMO de forma robusta"""
        if not TRACI_AVAILABLE:
            return
        try:
            # 1) Descobrir o binário primeiro
            sumo_binary = self.find_sumo_binary()
            if not sumo_binary:
                print("❌ Não foi possível encontrar o executável SUMO")
                return

            # 2) Se for Flatpak, rode via `flatpak run` para ter as libs corretas
            if isinstance(sumo_binary, str) and "/flatpak/app/org.eclipse.sumo/" in sumo_binary:
                base_cmd = ["flatpak", "run", "--command=sumo-gui", "org.eclipse.sumo"]
            else:
                base_cmd = [sumo_binary]

            # 3) Montar comando final
            cmd = base_cmd + [
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

        # 1) Tentar descobrir via PATH
        for binary in binaries:
            try:
                result = subprocess.run(["which", binary], capture_output=True, text=True)
                if result.returncode == 0:
                    return result.stdout.strip()
            except Exception:
                continue

        # 2) Verificar SUMO_HOME configurado (ex: instalação pkg no macOS)
        sumo_home = os.environ.get("SUMO_HOME")
        if sumo_home:
            for binary in binaries:
                candidate = os.path.join(sumo_home, "bin", binary)
                if os.path.exists(candidate):
                    return candidate

        # 3) Tentar caminhos absolutos comuns
        common_paths = [
            "/Library/Frameworks/EclipseSUMO.framework/Versions/Current/EclipseSUMO/bin/sumo",
            "/Library/Frameworks/EclipseSUMO.framework/Versions/Current/EclipseSUMO/bin/sumo-gui",
            "/Library/Frameworks/EclipseSUMO.framework/Versions/Current/EclipseSUMO/share/sumo/bin/sumo",
            "/Library/Frameworks/EclipseSUMO.framework/Versions/Current/EclipseSUMO/share/sumo/bin/sumo-gui",
            "/usr/bin/sumo",
            "/usr/local/bin/sumo",
            "/app/bin/sumo",  # Flatpak
            "/snap/bin/sumo",  # Snap
            "/var/lib/flatpak/app/org.eclipse.sumo/current/active/files/bin/sumo",
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

    async def notify_monitor(self, vehicle_id, position, speed, behaviour):
        """Enviar atualização para o agente monitor usando o comportamento chamador."""
        if not self.monitor_jid:
            return

        try:
            speed_value = float(speed)
        except (TypeError, ValueError):
            speed_value = speed

        if isinstance(position, (tuple, list)) and len(position) >= 2:
            position_str = f"{position[0]:.1f},{position[1]:.1f}"
        else:
            position_str = str(position)

        body = f"VEHICLE_UPDATE|{vehicle_id}|{position_str}|{speed_value}"
        msg = Message(to=self.monitor_jid)
        msg.body = body

        try:
            await behaviour.send(msg)
        except Exception as exc:
            print(f"⚠️ Erro ao enviar atualização para monitor: {exc}")

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
