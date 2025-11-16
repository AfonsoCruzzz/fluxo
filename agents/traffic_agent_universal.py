import asyncio
import spade
from spade.agent import Agent
from spade.behaviour import PeriodicBehaviour, CyclicBehaviour
from spade.message import Message
import os
import sys
import subprocess
import math

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
        sumo_config=os.path.join(current_dir, "sumo_files", "simple.sumocfg"),
        monitor_jid=None,
        vehicle_jid=None,
    ):
        super().__init__(jid, password)
        self.sumo_config = sumo_config
        self.simulation_process = None
        self.monitor_jid = monitor_jid
        self.vehicle_jid = vehicle_jid
        self.monitor_ready = False
        self.vehicle_ready = False
        self.clearance_duration = 2.0
        self.emergency_requests = {}
        self.emergency_vehicle_ids = set()
        self.emergency_hold_time = 15.0
        self.emergency_patterns = ("ambulance", "ambu", "fire", "brigade", "police")
        self.emergency_timeout_factor = 2.0
        self.real_behaviour = None
        self.sim_behaviour = None
        
    async def setup(self):
        print("🚦 Agente de Tráfego Universal Iniciado")
        print(f"📊 SUMO disponível: {SUMO_AVAILABLE}")
        print(f"📊 TRACI disponível: {TRACI_AVAILABLE}")
        
        self.add_behaviour(self.MonitorCommandListener())

        if TRACI_AVAILABLE and self.sumo_config:
            await self.start_simulation()
            self.real_behaviour = self.RealTrafficBehaviour(period=1.0)
            self.add_behaviour(self.real_behaviour)
        else:
            if self.vehicle_jid:
                print("🔶 Aguardando padrões fornecidos pelos VehicleAgents")
            else:
                print("🔶 Executando em modo simulado")
                self.sim_behaviour = self.SimulatedTrafficBehaviour(period=2.0)
                self.add_behaviour(self.sim_behaviour)
    
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
            self.min_skip_green = 0
            self.turn_angle_threshold = 35.0  # graus para diferenciar conversões
            self.opponent_clear_threshold = 2  # veículos tolerados no eixo oposto
            self.queue_difference_trigger = 5  # diferença mínima para preempção

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

                await self._activate_emergency_for_active(active_ids)
                self._collect_group_metrics()
                self._update_pass_threshold()
                self._honor_emergency_requests(sim_time, active_ids)

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

                    if data.get("mode") == "emergency":
                        continue

                    if self._skip_idle_phase(tl_id, data):
                        continue

                    if self._advance_if_lonely_vehicle(tl_id, data):
                        continue

                    self._adaptive_control(tl_id, data, sim_time)

                    if (
                        self.pass_threshold is not None
                        and data["vehicles_since_switch"] >= self.pass_threshold
                    ):
                        self._force_phase_change(tl_id, data, sim_time)

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
                    link_orientations = []
                    for link_group in controlled_links:
                        if not link_group:
                            link_orientations.append(None)
                            continue
                        # Cada grupo pode ter uma ou mais tuplas (incoming, outgoing, via)
                        incoming_lane = link_group[0][0]
                        for _, out_lane, _ in link_group:
                            if out_lane:
                                downstream_edges.add(out_lane.rsplit("_", 1)[0])
                        orientation = None
                        if incoming_lane:
                            orientation, _ = self._classify_lane(incoming_lane)
                        link_orientations.append(orientation)

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
                        "link_orientations": link_orientations,
                    }
                    print(
                        f"ℹ️ Controlando semáforo {tl_id} com {len(downstream_edges)} via(s) monitorada(s)"
                    )
                except traci.TraCIException as e:
                    print(f"⚠️ Falha ao inicializar semáforo {tl_id}: {e}")

        def _cleanup_observed(self, data, active_ids):
            data["observed_after_light"].intersection_update(active_ids)

        def _advance_if_lonely_vehicle(self, tl_id, data):
            try:
                lanes = traci.trafficlight.getControlledLanes(tl_id)
            except traci.TraCIException:
                return False

            if not lanes:
                return False

            axis_queue = {"EW": 0, "NS": 0}
            for lane_id in lanes:
                orientation, _ = self._classify_lane(lane_id)
                if orientation is None:
                    continue
                try:
                    queue = traci.lane.getLastStepHaltingNumber(lane_id)
                except traci.TraCIException:
                    queue = 0
                axis_queue[orientation] += queue

            ew = axis_queue["EW"]
            ns = axis_queue["NS"]
            chosen_axis = None
            reason = None

            if ew > 0 and ns == 0:
                chosen_axis = "EW"
                reason = "sem demanda oposta"
            elif ns > 0 and ew == 0:
                chosen_axis = "NS"
                reason = "sem demanda oposta"
            elif (
                ew - ns >= self.queue_difference_trigger
                and ns <= self.opponent_clear_threshold
            ):
                chosen_axis = "EW"
                reason = "diferença de fila"
            elif (
                ns - ew >= self.queue_difference_trigger
                and ew <= self.opponent_clear_threshold
            ):
                chosen_axis = "NS"
                reason = "diferença de fila"

            if not chosen_axis:
                return False

            try:
                traci.trafficlight.setPhaseDuration(tl_id, self.min_skip_green)
                data["vehicles_since_switch"] = 0
                print(
                    f"🟢 Semáforo {tl_id} acelerado (eixo {chosen_axis}) - {reason}"
                )
                return True
            except traci.TraCIException:
                return False

        def _skip_idle_phase(self, tl_id, data):
            axis_queue = self._axis_queue_for_light(tl_id)
            if not axis_queue:
                return False

            orientation = self._current_green_orientation(tl_id, data)
            if not orientation:
                return False

            current_queue = axis_queue.get(orientation, 0)
            other_axis = "NS" if orientation == "EW" else "EW"
            other_queue = axis_queue.get(other_axis, 0)

            if current_queue == 0 and other_queue > 0:
                try:
                    traci.trafficlight.setPhaseDuration(tl_id, self.min_skip_green)
                    data["vehicles_since_switch"] = 0
                    print(
                        f"⚡ Semáforo {tl_id} liberado para eixo {other_axis} (sem fila no atual)"
                    )
                    return True
                except traci.TraCIException:
                    return False
            return False

        def _axis_queue_for_light(self, tl_id):
            queues = {"EW": 0, "NS": 0}
            try:
                lanes = traci.trafficlight.getControlledLanes(tl_id)
            except traci.TraCIException:
                return queues

            for lane_id in lanes:
                orientation, _ = self._classify_lane(lane_id)
                if not orientation:
                    continue
                try:
                    queues[orientation] += traci.lane.getLastStepHaltingNumber(lane_id)
                except traci.TraCIException:
                    continue
            return queues

        def _current_green_orientation(self, tl_id, data):
            try:
                state = traci.trafficlight.getRedYellowGreenState(tl_id)
            except traci.TraCIException:
                return None

            orientations = data.get("link_orientations")
            if not orientations:
                return None

            ew_green = 0
            ns_green = 0
            for idx, char in enumerate(state):
                if char not in ("G", "g"):
                    continue
                if idx >= len(orientations):
                    continue
                orientation = orientations[idx]
                if orientation == "EW":
                    ew_green += 1
                elif orientation == "NS":
                    ns_green += 1

            if ew_green > ns_green and ew_green > 0:
                return "EW"
            if ns_green > ew_green and ns_green > 0:
                return "NS"
            return None

        def _prepare_lane_groups(self):
            groups = {
                "EW_MAIN": [],
                "EW_LEFT": [],
                "NS_MAIN": [],
                "NS_LEFT": [],
            }

            try:
                for tl_id in traci.trafficlight.getIDList():
                    for lane_id in traci.trafficlight.getControlledLanes(tl_id):
                        orientation, is_turn = self._classify_lane(lane_id)
                        if orientation is None:
                            continue
                        if orientation == "EW":
                            target = "EW_LEFT" if is_turn else "EW_MAIN"
                        else:
                            target = "NS_LEFT" if is_turn else "NS_MAIN"
                        if lane_id not in groups[target]:
                            groups[target].append(lane_id)
            except traci.TraCIException:
                pass

            self.lane_groups = groups
            print(f"🛣️ Grupos de faixas configurados automaticamente: {self.lane_groups}")

        def _classify_lane(self, lane_id):
            try:
                shape = traci.lane.getShape(lane_id)
            except traci.TraCIException:
                return None, None

            if len(shape) < 2:
                return None, None

            start = shape[0]
            end = shape[-1]
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            orientation = "EW" if abs(dx) >= abs(dy) else "NS"
            is_turn = self._lane_turn_angle(shape) >= self.turn_angle_threshold
            return orientation, is_turn

        def _lane_turn_angle(self, shape):
            if len(shape) < 3:
                return 0.0

            v_start = (shape[1][0] - shape[0][0], shape[1][1] - shape[0][1])
            v_end = (shape[-1][0] - shape[-2][0], shape[-1][1] - shape[-2][1])

            start_mag = math.hypot(*v_start)
            end_mag = math.hypot(*v_end)
            if not start_mag or not end_mag:
                return 0.0

            dot = v_start[0] * v_end[0] + v_start[1] * v_end[1]
            cosang = max(-1.0, min(1.0, dot / (start_mag * end_mag)))
            return math.degrees(math.acos(cosang))

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

        def _force_phase_change(self, tl_id, data, sim_time):
            try:
                current_phase = traci.trafficlight.getPhase(tl_id)
                phase_count = self._compute_phase_count(tl_id)
                if not phase_count or phase_count <= 1:
                    print(f"ℹ️ Semáforo {tl_id} possui fase única; ignorando troca forçada")
                    return
                candidate_phase = (current_phase + 1) % max(1, phase_count)
                next_phase = self._safe_phase_index(tl_id, candidate_phase)
                if next_phase is None:
                    print(f"ℹ️ Semáforo {tl_id} não aceita fase {candidate_phase}; mantendo estado atual")
                    return
                traci.trafficlight.setPhase(tl_id, next_phase)
                data["vehicles_since_switch"] = 0
                data["last_phase"] = next_phase
                data["last_phase_set_time"] = sim_time
                print(
                    f"🔁 Semáforo {tl_id} avançado para fase {next_phase} após {self.pass_threshold} veículos"
                )
            except traci.TraCIException as e:
                print(f"❌ Erro ao forçar troca do semáforo {tl_id}: {e}")

        def _compute_phase_count(self, tl_id):
            try:
                return traci.trafficlight.getPhaseNumber(tl_id)
            except AttributeError:
                pass

            try:
                definitions = traci.trafficlight.getCompleteRedYellowGreenDefinition(tl_id)
                if definitions:
                    return len(definitions[0].phases)
            except traci.TraCIException:
                pass
            return 1

        def _safe_phase_index(self, tl_id, phase_index):
            if phase_index is None:
                return None
            try:
                phase_count = traci.trafficlight.getPhaseNumber(tl_id)
            except (traci.TraCIException, AttributeError):
                phase_count = None

            if (
                phase_count is None
                or not isinstance(phase_count, int)
                or phase_count <= 0
            ):
                return None

            if phase_index < 0 or phase_index >= phase_count:
                return max(0, min(int(phase_index), phase_count - 1))
            return phase_index

        def _enforce_emergency_state(self, tl_id, request):
            data = self.tl_data.get(tl_id)
            if not data:
                return
            link_orientations = data.get("link_orientations")
            if not link_orientations:
                return

            orientation = request.get("orientation")
            if orientation is None:
                lane_id = request.get("lane_id")
                if lane_id:
                    orientation, _ = self._classify_lane(lane_id)
                    request["orientation"] = orientation

            link_index = request.get("link_index")
            state = ["r"] * len(link_orientations)
            changed = False

            for idx, link_orientation in enumerate(link_orientations):
                if orientation and link_orientation == orientation:
                    state[idx] = "G"
                    changed = True
                elif orientation is None and link_index is not None and idx == link_index:
                    state[idx] = "G"
                    changed = True

            if not changed and link_index is not None and link_index < len(state):
                state[link_index] = "G"
                changed = True

            if not changed:
                return

            state_str = "".join(state)
            try:
                traci.trafficlight.setRedYellowGreenState(tl_id, state_str)
            except traci.TraCIException as exc:
                print(f"⚠️ Falha ao ajustar estado manual do semáforo {tl_id}: {exc}")

        async def _activate_emergency_for_active(self, active_ids):
            if not active_ids or not TRACI_AVAILABLE:
                return

            for veh_id in active_ids:
                if veh_id in self.agent.emergency_vehicle_ids:
                    continue
                if self.agent.is_emergency_vehicle(veh_id):
                    print(f"🚨 Detectado veículo prioritário direto no controlador: {veh_id}")
                    await self.agent._handle_emergency_priority(veh_id)

        def _honor_emergency_requests(self, sim_time, active_ids):
            requests = getattr(self.agent, "emergency_requests", {})
            if not requests:
                return

            for tl_id, request in list(requests.items()):
                vehicle_id = request.get("vehicle_id")
                if not vehicle_id or vehicle_id not in active_ids:
                    self._release_emergency_request(
                        tl_id, request, reason="veículo ausente"
                    )
                    continue

                activated_at = request.get("activated_at")
                hold_time = request.get("hold_time", self.agent.emergency_hold_time)
                if (
                    request.get("last_clearance")
                    and sim_time - request["last_clearance"] < self.clearance_duration
                ):
                    continue
                max_duration = request.get(
                    "max_duration", hold_time * self.agent.emergency_timeout_factor
                )
                if (
                    activated_at is not None
                    and max_duration is not None
                    and sim_time - activated_at >= max_duration
                ):
                    self._release_emergency_request(
                        tl_id, request, reason="tempo de prioridade excedido"
                    )
                    continue

                try:
                    tls_info = traci.vehicle.getNextTLS(vehicle_id)
                except traci.TraCIException:
                    self._release_emergency_request(
                        tl_id, request, reason="falha ao obter próximo semáforo"
                    )
                    continue

                if not tls_info:
                    self._release_emergency_request(
                        tl_id, request, reason="sem novos semáforos à frente"
                    )
                    continue

                next_id, link_index, _, _ = tls_info[0]
                if next_id != tl_id:
                    self._release_emergency_request(
                        tl_id,
                        request,
                        reason=f"{vehicle_id} já cruzou {tl_id}",
                        keep_vehicle=True,
                    )
                    hold_time = request.get("hold_time", self.agent.emergency_hold_time)
                    self.agent._schedule_emergency_request(
                        vehicle_id,
                        next_id,
                        link_index,
                        hold_time=hold_time,
                    )
                    continue

                data = self.tl_data.get(tl_id)
                if data and data.get("mode") != "emergency":
                    data["mode"] = "emergency"
                    print(f"🚨 Semáforo {tl_id} priorizando {vehicle_id}")

                hold_time = request.get("hold_time", self.agent.emergency_hold_time)
                target_phase = self._safe_phase_index(
                    tl_id, request.get("phase_index")
                )
                request["phase_index"] = target_phase

                try:
                    current_phase = traci.trafficlight.getPhase(tl_id)
                    if target_phase is not None and current_phase != target_phase:
                        traci.trafficlight.setPhase(tl_id, target_phase)
                        current_phase = target_phase
                    traci.trafficlight.setPhaseDuration(tl_id, hold_time)
                    self._enforce_emergency_state(tl_id, request)
                    if data:
                        data["last_phase"] = current_phase
                        data["last_phase_set_time"] = sim_time
                        data["vehicles_since_switch"] = 0
                except traci.TraCIException as exc:
                    print(f"⚠️ Falha ao manter prioridade no semáforo {tl_id}: {exc}")

        def _release_emergency_request(self, tl_id, request, reason="", keep_vehicle=False):
            removed = self.agent.emergency_requests.pop(tl_id, None)
            if removed and reason:
                print(f"✅ Semáforo {tl_id} deixou modo emergência ({reason})")

            data = self.tl_data.get(tl_id)
            if data and data.get("mode") == "emergency":
                data["mode"] = "adaptive"
                default_program = data.get("default_program")
                if default_program:
                    try:
                        traci.trafficlight.setProgram(tl_id, default_program)
                    except traci.TraCIException:
                        pass

            if not keep_vehicle:
                vehicle_id = request.get("vehicle_id")
                if vehicle_id:
                    self.agent.emergency_vehicle_ids.discard(vehicle_id)
    
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

    class MonitorCommandListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=1)
            if not msg or not msg.body:
                return

            if msg.body.startswith("TRAFFIC_ALERT"):
                parts = msg.body.split("|")
                if len(parts) < 3:
                    return
                vehicle_id = parts[1]
                status = parts[2]
                await self.agent.handle_monitor_alert(vehicle_id, status)
            elif msg.body.startswith("AGENT_READY"):
                parts = msg.body.split("|")
                if len(parts) >= 2:
                    agent_type = parts[1]
                    self.agent.mark_agent_ready(agent_type)
            elif msg.body.startswith("VEHICLE_COMMAND"):
                parts = msg.body.split("|")
                if len(parts) < 3:
                    return
                vehicle_id = parts[1]
                command = parts[2]
                await self.agent.handle_vehicle_command(vehicle_id, command)
            elif msg.body.startswith("VEHICLE_REPORT"):
                parts = msg.body.split("|")
                if len(parts) < 4:
                    return
                vehicle_id = parts[1]
                position = parts[2]
                speed = parts[3]
                await self.agent.handle_external_vehicle_update(
                    vehicle_id, position, speed, self
                )
    
    async def start_simulation(self):
        """Iniciar simulação SUMO"""
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
        """Encontrar executável SUMO"""
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

    async def handle_monitor_alert(self, vehicle_id, status):
        if status == "emergency":
            await self._handle_emergency_priority(vehicle_id)
            return

        if status != "lento":
            return

        print(f"📨 Controlador recebeu alerta de veículo lento: {vehicle_id}")

        if not TRACI_AVAILABLE:
            print("ℹ️  Sem TRACI disponível; alerta registrado apenas para logging")
            return

        try:
            next_tls = traci.vehicle.getNextTLS(vehicle_id)
            if not next_tls:
                print(f"ℹ️  {vehicle_id} não possui semáforo à frente para priorizar")
                return

            tl_id = next_tls[0][0]
            self._force_priority_green(tl_id)
            print(f"🟢 Semáforo {tl_id} ajustado para priorizar {vehicle_id}")
        except traci.TraCIException as exc:
            print(f"⚠️  Falha ao priorizar veículo {vehicle_id}: {exc}")

    def _force_priority_green(self, tl_id, duration=15):
        try:
            traci.trafficlight.setPhase(tl_id, 0)
            traci.trafficlight.setPhaseDuration(tl_id, duration)
        except traci.TraCIException as exc:
            print(f"⚠️  Não foi possível ajustar semáforo {tl_id}: {exc}")

    def mark_agent_ready(self, agent_type):
        if agent_type == "monitor":
            self.monitor_ready = True
            print("📡 Monitor confirmado como pronto.")
        elif agent_type == "vehicle":
            self.vehicle_ready = True
            print("🚗 VehicleAgent confirmado como pronto.")

    async def handle_vehicle_command(self, vehicle_id, command):
        if command == "REQUEST_PRIORITY":
            print(f"🚨 Solicitação direta de prioridade recebida para {vehicle_id}")
            await self._handle_emergency_priority(vehicle_id)
        elif command == "CLEAR_PRIORITY":
            behaviour = getattr(self, "real_behaviour", None)
            if not behaviour:
                return
            for tl_id, request in list(self.emergency_requests.items()):
                if request.get("vehicle_id") == vehicle_id:
                    behaviour._release_emergency_request(
                        tl_id, request, reason="veículo liberado"
                    )

    async def handle_external_vehicle_update(self, vehicle_id, position, speed, behaviour):
        try:
            x_str, y_str = position.split(",")
            pos_tuple = (float(x_str), float(y_str))
        except ValueError:
            pos_tuple = position

        try:
            speed_value = float(speed)
        except ValueError:
            speed_value = speed

        await self.notify_monitor(vehicle_id, pos_tuple, speed_value, behaviour)

    async def _handle_emergency_priority(self, vehicle_id):
        if not TRACI_AVAILABLE:
            print("ℹ️  Sem TRACI disponível; impossível priorizar veículo de emergência")
            return

        self.emergency_vehicle_ids.add(vehicle_id)

        try:
            next_tls = traci.vehicle.getNextTLS(vehicle_id)
        except traci.TraCIException as exc:
            print(f"⚠️  Não foi possível localizar semáforos para {vehicle_id}: {exc}")
            return

        if not next_tls:
            print(f"ℹ️  {vehicle_id} não possui semáforos no trajeto imediato")
            return

        max_targets = 3
        scheduled = 0
        for tl_info in next_tls:
            tl_id, link_index, distance, _ = tl_info
            self._schedule_emergency_request(
                vehicle_id, tl_id, link_index, distance=distance
            )
            scheduled += 1
            if scheduled >= max_targets:
                break

    def _schedule_emergency_request(
        self, vehicle_id, tl_id, link_index, hold_time=None, distance=None
    ):
        if not TRACI_AVAILABLE:
            return

        hold = hold_time or self.emergency_hold_time
        if distance is not None:
            try:
                current_speed = traci.vehicle.getSpeed(vehicle_id)
            except traci.TraCIException:
                current_speed = None
            base_speed = current_speed if current_speed and current_speed > 2.0 else 10.0
            travel_time = distance / max(base_speed, 0.1)
            hold = max(hold, travel_time + self.emergency_hold_time * 0.25)
        phase_index = self._find_phase_for_link(tl_id, link_index)
        clearance_delay = self.clearance_duration
        request = {
            "vehicle_id": vehicle_id,
            "phase_index": phase_index,
            "link_index": link_index,
            "hold_time": hold,
            "lane_id": None,
            "orientation": None,
            "activated_at": None,
            "max_duration": None,
            "distance": distance,
            "last_clearance": self._current_simulation_time() if clearance_delay else None,
        }
        orientation, lane_id = self._orientation_for_vehicle(vehicle_id)
        request["orientation"] = orientation
        request["lane_id"] = lane_id
        request["activated_at"] = self._current_simulation_time()
        request["max_duration"] = hold * self.emergency_timeout_factor
        self.emergency_requests[tl_id] = request
        print(
            f"🚨 Controller: prioridade registrada para {vehicle_id} no semáforo {tl_id}"
        )
        self._apply_emergency_phase(tl_id, request)
        return request

    def _apply_emergency_phase(self, tl_id, request):
        phase_index = request.get("phase_index")
        hold_time = request.get("hold_time", self.emergency_hold_time)
        try:
            if phase_index is not None:
                try:
                    phase_count = traci.trafficlight.getPhaseNumber(tl_id)
                except (traci.TraCIException, AttributeError):
                    phase_count = None

                if (
                    phase_count is None
                    or not isinstance(phase_count, int)
                    or phase_count <= 0
                ):
                    phase_index = None
                elif phase_index < 0 or phase_index >= phase_count:
                    phase_index = max(0, min(int(phase_index), phase_count - 1))

                if phase_index is not None:
                    traci.trafficlight.setPhase(tl_id, phase_index)
                    traci.trafficlight.setPhaseDuration(tl_id, hold_time)
                    request["phase_index"] = phase_index
                else:
                    self._force_priority_green(tl_id, duration=hold_time)
            else:
                self._force_priority_green(tl_id, duration=hold_time)
            behaviour = getattr(self, "real_behaviour", None)
            if behaviour:
                behaviour._enforce_emergency_state(tl_id, request)
        except traci.TraCIException as exc:
            print(f"⚠️  Falha ao aplicar modo emergência no semáforo {tl_id}: {exc}")

    def _find_phase_for_link(self, tl_id, link_index):
        if link_index is None:
            return None

        try:
            definitions = traci.trafficlight.getCompleteRedYellowGreenDefinition(tl_id)
        except traci.TraCIException:
            return None

        if not definitions:
            return None

        phases = definitions[0].phases
        for idx, phase in enumerate(phases):
            state = getattr(phase, "state", "")
            if link_index < len(state) and state[link_index] in ("G", "g"):
                return idx
        return None

    def _orientation_for_vehicle(self, vehicle_id):
        lane_id = None
        orientation = None

        try:
            lane_id = traci.vehicle.getLaneID(vehicle_id)
        except traci.TraCIException:
            lane_id = None

        if lane_id:
            orientation = self._lane_orientation_from_lane(lane_id)
        return orientation, lane_id

    def _lane_orientation_from_lane(self, lane_id):
        try:
            shape = traci.lane.getShape(lane_id)
        except traci.TraCIException:
            return None

        if len(shape) < 2:
            return None

        dx = shape[-1][0] - shape[0][0]
        dy = shape[-1][1] - shape[0][1]
        return "EW" if abs(dx) >= abs(dy) else "NS"

    def is_emergency_vehicle(self, vehicle_id):
        if not vehicle_id:
            return False
        lower = vehicle_id.lower()
        return any(pattern in lower for pattern in self.emergency_patterns)

    def _current_simulation_time(self):
        if not TRACI_AVAILABLE:
            return None
        try:
            return traci.simulation.getTime()
        except traci.TraCIException:
            return None

    async def notify_monitor(self, vehicle_id, position, speed, behaviour):
        """Enviar atualização para agentes inscritos (monitor/veículos)."""
        recipients = []
        if self.monitor_jid and self.monitor_ready:
            recipients.append(self.monitor_jid)
        if self.vehicle_jid and self.vehicle_ready:
            recipients.append(self.vehicle_jid)
        if not recipients:
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

        for jid in recipients:
            msg = Message(to=jid)
            msg.body = body
            try:
                await behaviour.send(msg)
            except Exception as exc:
                print(f"⚠️ Erro ao enviar atualização para {jid}: {exc}")

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
