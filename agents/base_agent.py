import numpy


class BaseAgent:
    def action(self, observation: numpy.ndarray) -> numpy.ndarray:
        return

    def reward(self, reward: float, terminated: bool) -> None:
        return