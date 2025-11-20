from __future__ import annotations

import random
from typing import Dict, Optional, Sequence

import traci

# Predefined routes on the grid. They avoid needing vehicles in the XML while still exercising intersections.
DEFAULT_ROUTES: Dict[str, Sequence[str]] = {
    "north_south_center": ("C4C3", "C3C2", "C2C1", "C1C0"),
    "south_north_center": ("C0C1", "C1C2", "C2C3", "C3C4"),
    "west_east_mid": ("A2B2", "B2C2", "C2D2", "D2E2"),
    "east_west_mid": ("E2D2", "D2C2", "C2B2", "B2A2"),
}


class VehicleAgent:
    """Simple vehicle generator that injects cars on predefined routes."""

    def __init__(self, routes: Optional[Dict[str, Sequence[str]]] = None, spawn_interval: int = 10) -> None:
        self.routes = routes or DEFAULT_ROUTES
        self.spawn_interval = max(1, spawn_interval)
        self.last_spawn_step = -self.spawn_interval
        self.counter = 0

        self._ensure_routes()

    def _ensure_routes(self) -> None:
        existing = set(traci.route.getIDList())
        for route_id, edges in self.routes.items():
            if route_id in existing:
                continue
            traci.route.add(route_id, edges)

    def step(self, step_index: int) -> None:
        """Spawn one vehicle every `spawn_interval` simulation steps."""
        if (step_index - self.last_spawn_step) < self.spawn_interval:
            return

        self.last_spawn_step = step_index
        route_id = random.choice(list(self.routes.keys()))
        veh_id = f"veh{self.counter}"
        self.counter += 1

        try:
            traci.vehicle.add(veh_id, route_id, typeID="DEFAULT_VEHTYPE", departLane="best", departSpeed="max")
        except traci.TraCIException as exc:
            print(f"⚠️ Erro ao adicionar veículo {veh_id} na rota {route_id}: {exc}")
