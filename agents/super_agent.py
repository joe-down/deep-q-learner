import typing

import torch
import copy
import numpy
import itertools

from agents.agent import Agent
from agents.base_agent import BaseAgent


class SuperAgent(BaseAgent):
    OBSERVATION_LENGTH: int = 4
    ACTION_LENGTH: int = 1
    POSSIBLE_ACTIONS = torch.tensor([0, 1])
    NN_INPUT: int = OBSERVATION_LENGTH + ACTION_LENGTH

    def __init__(self,
                 train_agent_count: int,
                 save_path: str,
                 nn_width: int,
                 discount_factor: float,
                 train_batch_size: int,
                 target_network_update_time: int,
                 buffer_size: int,
                 random_action_probability_decay: float) -> None:
        self.__agents = [Agent(super_agent=self,
                               observation_length=self.OBSERVATION_LENGTH,
                               action_length=self.ACTION_LENGTH,
                               buffer_size=buffer_size,
                               random_action_probability_decay=random_action_probability_decay)
                         for _ in range(train_agent_count)]
        self.__save_path = save_path
        self.__nn_width = nn_width
        self.__discount_factor = discount_factor
        self.__train_batch_size = train_batch_size
        self.__target_network_update_time = target_network_update_time

        self.__neural_network: torch.nn.Sequential = torch.nn.Sequential(
            torch.nn.Linear(self.NN_INPUT, self.__nn_width),
            torch.nn.ReLU(),
            torch.nn.Linear(self.__nn_width, self.__nn_width),
            torch.nn.ReLU(),
            torch.nn.Linear(self.__nn_width, self.__nn_width),
            torch.nn.ReLU(),
            torch.nn.Linear(self.__nn_width, 1),
        )
        try:
            self.__neural_network.load_state_dict(torch.load(self.__save_path))
            print("model loaded")
        except FileNotFoundError:
            self.__neural_network.apply(self.neural_network_initialisation)
            print("model initialised")

        self.__target_neural_network = copy.deepcopy(self.__neural_network)
        self.target_neural_network_update_counter: int = 0
        self.optimiser: torch.optim.Optimizer = torch.optim.Adam(params=self.__neural_network.parameters())
        self.loss_function: torch.nn.MSELoss = torch.nn.MSELoss()

        # Action spaces
        combinations = itertools.combinations_with_replacement(self.POSSIBLE_ACTIONS, self.ACTION_LENGTH)
        permutations = (torch.tensor(tuple(itertools.permutations(combination))).unique(dim=0)
                        for combination in combinations)
        self.__action_space = torch.concatenate(tuple(permutations), dim=0)
        assert self.__action_space.dim() == 2 and self.__action_space.shape[1] == self.ACTION_LENGTH
        self.train_action_space: torch.tensor = self.__action_space.repeat(self.__train_batch_size, 1, 1)
        assert self.train_action_space.shape == (
            self.__train_batch_size, self.__action_space.shape[0], self.ACTION_LENGTH)

    @property
    def agents(self) -> list[Agent]:
        return self.__agents

    @property
    def action_space(self) -> torch.Tensor:
        return self.__action_space

    @property
    def training(self) -> bool:
        return len(self.__agents) > 0

    @staticmethod
    def neural_network_initialisation(module):
        if isinstance(module, torch.nn.Linear):
            torch.nn.init.xavier_uniform_(module.weight)

    def state_dict(self) -> dict[str, typing.Any]:
        return self.__neural_network.state_dict()

    def base_action(self, observation: numpy.ndarray) -> tuple[torch.Tensor, torch.Tensor]:
        assert observation.shape == (self.OBSERVATION_LENGTH,)
        observation = torch.tensor(observation)

        observation_actions = torch.concatenate((observation.repeat(self.action_space.shape[0], 1), self.action_space),
                                                1)
        best_expected_reward_action_index = self.__neural_network.forward(observation_actions).argmax()
        best_action = self.action_space[best_expected_reward_action_index]
        observation_action = observation_actions[best_expected_reward_action_index]

        assert observation_action.shape == (self.NN_INPUT,)
        assert best_action.shape == (self.ACTION_LENGTH,)
        assert min(best_action) >= -1
        assert max(best_action) <= 1
        return best_action, observation_action

    def action(self, observation: numpy.ndarray) -> numpy.ndarray:
        best_action, observation_action = self.base_action(observation=observation)
        return best_action.cpu().numpy()

    def train(self) -> float:
        if not self.training:
            return 0
        ready_agents = torch.tensor([agent_id for agent_id, agent in enumerate(self.__agents) if agent.buffer_ready()])
        if len(ready_agents) < 1:
            return 0
        batch_agents = ready_agents[torch.randint(high=len(ready_agents), size=(self.__train_batch_size,))]
        (observation_actions,
         next_observation_actions,
         immediate_rewards,
         terminations) = self.__agents[batch_agents[0]].random_observations(number=1)
        for agent_id in batch_agents[1:]:
            (current_observation_actions,
             current_next_observation_actions,
             current_immediate_rewards,
             current_terminations) = self.__agents[agent_id].random_observations(number=1)
            observation_actions = torch.concatenate((observation_actions, current_observation_actions))
            next_observation_actions = torch.concatenate((next_observation_actions, current_next_observation_actions))
            immediate_rewards = torch.concatenate((immediate_rewards, current_immediate_rewards))
            terminations = torch.concatenate((terminations, current_terminations))

        next_observations = next_observation_actions[:, :-self.ACTION_LENGTH]
        assert next_observations.shape == (self.__train_batch_size, self.OBSERVATION_LENGTH)
        a = next_observations.unsqueeze(1).repeat(1, self.train_action_space.shape[1], 1)
        assert a.shape == (self.__train_batch_size, self.train_action_space.shape[1], self.OBSERVATION_LENGTH)
        b = torch.concatenate((a, self.train_action_space), 2)
        assert b.shape == (self.__train_batch_size, self.train_action_space.shape[1], self.NN_INPUT)
        b_flat = b.flatten(0, 1)
        assert b_flat.shape == (self.__train_batch_size * self.train_action_space.shape[1], self.NN_INPUT)
        b_2 = self.__neural_network(b_flat)
        assert b_2.shape == (self.__train_batch_size * self.train_action_space.shape[1], 1)
        c = b_2.unflatten(0, b.shape[:2])
        assert c.shape == (self.__train_batch_size, self.train_action_space.shape[1], 1)
        best_next_action_indexes = c.argmax(1).squeeze(1)
        assert best_next_action_indexes.shape == (self.__train_batch_size,)
        best_next_actions = self.action_space[best_next_action_indexes]
        assert best_next_actions.shape == (self.__train_batch_size, self.ACTION_LENGTH)
        best_next_observation_actions = torch.concatenate((next_observations, best_next_actions), dim=1)
        assert best_next_observation_actions.shape == (self.__train_batch_size, self.NN_INPUT)
        # Learn
        target = (immediate_rewards + self.__discount_factor * (1 - terminations)
                  * self.__target_neural_network(best_next_observation_actions))
        prediction = self.__neural_network(observation_actions)
        self.optimiser.zero_grad()
        loss = self.loss_function(target, prediction)
        loss.backward()
        self.optimiser.step()
        # Update target network
        self.target_neural_network_update_counter = ((self.target_neural_network_update_counter + 1)
                                                     % self.__target_network_update_time)
        if self.target_neural_network_update_counter == 0:
            self.__target_neural_network = copy.deepcopy(self.__neural_network)
        return float(loss)
