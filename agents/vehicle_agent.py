import asyncio
import math
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, OneShotBehaviour, PeriodicBehaviour
from spade.message import Message
from spade.template import Template


class VehicleAgent(Agent):
    def __init__(
        self,
        jid,
        password,
        controller_jid=None,
        monitor_jid=None,
        tracked_vehicles=None,
        pattern_routes=None,
        pattern_period=1.0,
        wait_speed_threshold=2.0,
        wait_time_threshold=10.0,
    ):
        super().__init__(jid, password)
        self.controller_jid = controller_jid
        self.monitor_jid = monitor_jid
        self.tracked_vehicles = set(tracked_vehicles or [])
        self.pending_requests = {}
        self.pattern_routes = pattern_routes or []
        self.pattern_period = pattern_period
        self.wait_speed_threshold = wait_speed_threshold
        self.wait_time_threshold = wait_time_threshold
        self.vehicle_state = {}

    class VehicleListener(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if not msg or not msg.body:
                return

            if msg.body.startswith("VEHICLE_UPDATE"):
                parts = msg.body.split("|")
                if len(parts) < 4:
                    return
                vehicle_id = parts[1]
                speed = float(parts[3])
                await self.agent.handle_vehicle_update(vehicle_id, speed, self)

    class TrafficPatternBehaviour(PeriodicBehaviour):
        def __init__(self, period, patterns):
            super().__init__(period)
            if isinstance(period, (int, float)):
                self.period_seconds = float(period)
            else:
                self.period_seconds = float(period.total_seconds())
            self.patterns = patterns
            self.spawn_clock = {pat["id_prefix"]: 0.0 for pat in patterns}
            self.counters = {pat["id_prefix"]: 0 for pat in patterns}
            self.active = []

        async def run(self):
            if not self.patterns:
                return

            # Atualizar relógio de spawn para cada padrão
            for pattern in self.patterns:
                prefix = pattern["id_prefix"]
                interval = float(pattern.get("spawn_interval", 8.0))
                self.spawn_clock[prefix] += self.period_seconds
                while self.spawn_clock[prefix] >= interval:
                    self.spawn_clock[prefix] -= interval
                    vehicle = self._spawn_vehicle(pattern)
                    if vehicle:
                        self.active.append(vehicle)
                        if vehicle.get("priority"):
                            await self.agent._notify_controller(
                                vehicle["id"], "REQUEST_PRIORITY", self
                            )

            # Atualizar veículos ativos
            for vehicle in list(self.active):
                vehicle["progress"] += vehicle["speed"] * self.period_seconds
                if vehicle["progress"] >= vehicle["distance"]:
                    self.active.remove(vehicle)
                    if vehicle.get("priority"):
                        await self.agent._notify_controller(
                            vehicle["id"], "CLEAR_PRIORITY", self
                        )
                        self.agent.tracked_vehicles.discard(vehicle["id"])
                    continue

                position = (
                    vehicle["start"][0] + vehicle["direction"][0] * vehicle["progress"],
                    vehicle["start"][1] + vehicle["direction"][1] * vehicle["progress"],
                )
                await self.agent._send_vehicle_report(
                    vehicle["id"], position, vehicle["speed"], self
                )

        def _spawn_vehicle(self, pattern):
            start = pattern["start"]
            end = pattern["end"]
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            distance = math.hypot(dx, dy)
            if distance == 0:
                return None
            direction = (dx / distance, dy / distance)

            prefix = pattern["id_prefix"]
            idx = self.counters[prefix]
            self.counters[prefix] += 1
            vehicle_type = pattern.get("vehicle_type", "car")
            vehicle_id = f"{prefix}{idx}"
            speed = float(pattern.get("speed", 12.0))

            if vehicle_type == "ambulance":
                vehicle_id = f"ambulance{idx}"

            vehicle = {
                "id": vehicle_id,
                "start": start,
                "direction": direction,
                "distance": distance,
                "speed": speed,
                "progress": 0.0,
                "priority": pattern.get("priority", vehicle_type == "ambulance"),
            }
            if vehicle["priority"]:
                self.agent.tracked_vehicles.add(vehicle_id)
            return vehicle

    async def handle_vehicle_update(self, vehicle_id, speed, behaviour):
        # ✅ Feature 3 (Vehicle Agents): monitor every vehicle and act on long waits
        if self.tracked_vehicles and vehicle_id not in self.tracked_vehicles:
            return

        now = asyncio.get_event_loop().time()
        state = self.vehicle_state.setdefault(
            vehicle_id,
            {"last_time": now, "waiting_time": 0.0, "requested": False},
        )
        delta = max(0.0, now - state["last_time"])
        state["last_time"] = now

        if speed <= self.wait_speed_threshold:
            state["waiting_time"] += delta
            await self._report_waiting(vehicle_id, state["waiting_time"], behaviour)
            if (
                state["waiting_time"] >= self.wait_time_threshold
                and not state["requested"]
            ):
                await self._notify_controller(vehicle_id, "REQUEST_PRIORITY", behaviour)
                state["requested"] = True
                self.pending_requests[vehicle_id] = now
        else:
            state["waiting_time"] = 0.0
            if state["requested"]:
                await self._notify_controller(vehicle_id, "CLEAR_PRIORITY", behaviour)
                state["requested"] = False
                self.pending_requests.pop(vehicle_id, None)

    async def _notify_controller(self, vehicle_id, command, behaviour):
        if not self.controller_jid:
            return

        msg = Message(to=self.controller_jid)
        msg.body = f"VEHICLE_COMMAND|{vehicle_id}|{command}"
        try:
            await behaviour.send(msg)
            print(
                f"🚙 VEHICLE_AGENT: comando '{command}' enviado para controlador ({vehicle_id})"
            )
        except Exception as exc:
            print(f"⚠️ VehicleAgent falhou ao enviar comando: {exc}")

    async def _send_vehicle_report(self, vehicle_id, position, speed, behaviour):
        if not self.controller_jid:
            return
        msg = Message(to=self.controller_jid)
        msg.body = (
            f"VEHICLE_REPORT|{vehicle_id}|{position[0]:.1f},{position[1]:.1f}|{speed:.1f}"
        )
        try:
            await behaviour.send(msg)
        except Exception as exc:
            print(f"⚠️ VehicleAgent não conseguiu enviar relatório: {exc}")

    async def _report_waiting(self, vehicle_id, waiting_time, behaviour):
        if not self.monitor_jid:
            return
        msg = Message(to=self.monitor_jid)
        msg.body = f"VEHICLE_WAIT|{vehicle_id}|{waiting_time:.1f}"
        try:
            await behaviour.send(msg)
        except Exception:
            pass

    async def setup(self):
        print("🚙 Iniciando VehicleAgent...")
        template = Template()
        self.add_behaviour(self.VehicleListener(), template=template)
        if self.pattern_routes:
            self.add_behaviour(
                self.TrafficPatternBehaviour(self.pattern_period, self.pattern_routes)
            )
        await self._notify_ready()

    class NotifyReadyBehaviour(OneShotBehaviour):
        async def run(self):
            controller = self.agent.controller_jid
            if not controller:
                return
            msg = Message(to=controller)
            msg.body = "AGENT_READY|vehicle"
            try:
                await self.send(msg)
            except Exception as exc:
                print(f"⚠️ VehicleAgent não conseguiu avisar controlador: {exc}")

    async def _notify_ready(self):
        self.add_behaviour(self.NotifyReadyBehaviour())
