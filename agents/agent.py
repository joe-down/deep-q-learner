import typing

import numpy
import torch

from agents.base_agent import BaseAgent
from agents.buffer import Buffer

if typing.TYPE_CHECKING:
    from agents.super_agent import SuperAgent


class Agent(BaseAgent):
    def __init__(self,
                 super_agent: "SuperAgent",
                 observation_length: int,
                 action_length: int,
                 buffer_size: int,
                 random_action_probability_decay: float) -> None:
        self.__super_agent = super_agent
        self.__observation_length = observation_length
        self.__action_length = action_length
        self.__nn_input_length = self.__observation_length + self.__action_length
        self.__buffer = Buffer(nn_input=self.__nn_input_length, buffer_size=buffer_size)

        self.__random_action_probability = 1
        self.__random_action_probability_decay = random_action_probability_decay
        self.__minimum_random_action_probability = 0

    @property
    def random_action_probability(self) -> float:
        return self.__random_action_probability

    @property
    def minimum_random_action_probability(self) -> float:
        return self.__minimum_random_action_probability

    @minimum_random_action_probability.setter
    def minimum_random_action_probability(self, value: float) -> None:
        assert 0 <= value <= 1
        self.__minimum_random_action_probability = value

    def action(self, observation: numpy.ndarray) -> numpy.ndarray:
        assert observation.shape == (self.__observation_length,)

        if torch.rand(1) > self.__random_action_probability:
            best_action, observation_action = self.__super_agent.base_action(observation=observation)
        else:
            best_action = torch.rand((self.__action_length,))
            observation_action = torch.concatenate((torch.tensor(observation), best_action))

        assert best_action.shape == (self.__action_length,)
        assert observation_action.shape == (self.__nn_input_length,)
        self.__buffer.push_observation(observation=observation_action)
        self.__random_action_probability = max(self.__random_action_probability
                                               * self.__random_action_probability_decay,
                                               self.__minimum_random_action_probability)
        return best_action.cpu().numpy()

    def reward(self, reward: float, terminated: bool) -> None:
        self.__buffer.push_reward(reward=reward, terminated=terminated)

    def buffer_ready(self) -> bool:
        return self.__buffer.buffer_observations_ready()

    def random_observations(self, number: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        return self.__buffer.random_observations(number=number)
