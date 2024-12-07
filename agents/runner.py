import typing

import numpy
import gymnasium
import torch

from agents.actor_critic.actor import Actor
from agents.basic_agent import BasicAgent


class Runner:
    def __init__(self,
                 env: gymnasium.Env,
                 agent: BasicAgent,
                 seed: int,
                 action_formatter: typing.Callable[[torch.Tensor], torch.Tensor],
                 ) -> None:
        self.__env = env
        self.__agent = agent
        self.__seed = seed
        self.__action_formatter = action_formatter
        self.__observation: numpy.ndarray
        self.__observation, info = self.__env.reset(seed=self.__seed)

    def close(self) -> None:
        self.__env.close()

    def step(self, actor: Actor) -> tuple[bool, float]:
        action = self.__action_formatter(self.__agent.action(self.__observation, actor=actor).squeeze()).cpu().numpy()
        self.__observation, reward, terminated, truncated, info = self.__env.step(action)
        reward = reward.__float__()
        dead = terminated or truncated
        self.__agent.reward(reward, terminated=dead)
        if dead:
            self.__observation, info = self.__env.reset()
        return dead, reward

    def run_full(self, actor: Actor) -> float:
        accumulated_reward = 0
        dead = False
        while not dead:
            dead, reward = self.step(actor=actor)
            accumulated_reward += reward
        return accumulated_reward
