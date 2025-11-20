from __future__ import annotations

from typing import List

import traci


class TrafficLightAgent:
    """
    One agent per traffic light controller.
    It cycles through the existing SUMO phase program instead of using global coordination.
    """

    def __init__(self, tl_id: str) -> None:
        self.tl_id = tl_id
        self.phases: List = []
        self.current_phase_index: int = 0
        self.remaining_steps: int = 0

    def initialize(self) -> None:
        """Read the configured logic from SUMO and set the initial phase."""
        logics = traci.trafficlight.getAllProgramLogics(self.tl_id)
        if logics:
            self.phases = logics[0].phases

        if not self.phases:
            return

        self.current_phase_index = 0
        self.remaining_steps = max(1, int(round(self.phases[0].duration)))
        traci.trafficlight.setRedYellowGreenState(self.tl_id, self.phases[0].state)

    def step(self) -> None:
        """Advance to the next phase when the timer expires."""
        if not self.phases:
            return

        if self.remaining_steps <= 0:
            self.current_phase_index = (self.current_phase_index + 1) % len(self.phases)
            phase = self.phases[self.current_phase_index]
            self.remaining_steps = max(1, int(round(phase.duration)))
            traci.trafficlight.setRedYellowGreenState(self.tl_id, phase.state)

        self.remaining_steps -= 1
