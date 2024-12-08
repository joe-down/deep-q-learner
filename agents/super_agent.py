import pathlib
import typing

import gymnasium
import numpy
import torch
from agents.actor_critic.actor import Actor
from agents.actor_critic.critic import Critic
from agents.buffer import Buffer
from agents.runner import Runner


class SuperAgent:
    def __init__(self,
                 train_agent_count: int,
                 save_path: pathlib.Path,
                 environment: str,
                 seed: int,
                 actor_nn_width: int,
                 actor_nn_depth: int,
                 critic_nn_width: int,
                 critic_nn_depth: int,
                 discount_factor: float,
                 train_batch_size: int,
                 buffer_size: int,
                 random_action_probability: float,
                 minimum_random_action_probability: float,
                 random_action_probability_decay: float,
                 observation_length: int,
                 action_length: int,
                 target_update_proportion: float,
                 noise_variance: float,
                 action_formatter: typing.Callable[[torch.Tensor], torch.Tensor],
                 ) -> None:
        self.__action_length = action_length
        self.__discount_factor = discount_factor
        self.__train_batch_size = train_batch_size
        self.__target_update_proportion = target_update_proportion
        self.__noise_variance = noise_variance
        self.__random_action_probability_decay = random_action_probability_decay
        self.__critic = Critic(
            load_path=save_path,
            observation_length=observation_length,
            action_length=action_length,
            nn_width=critic_nn_width,
            nn_depth=critic_nn_depth,
        )
        self.__actor = Actor(
            load_path=save_path,
            observation_length=observation_length,
            action_length=action_length,
            nn_width=actor_nn_width,
            nn_depth=actor_nn_depth,
        )
        self.__runners = [Runner(
            env=gymnasium.make(environment, render_mode=None),
            seed=seed + runner_index,
            action_formatter=action_formatter,
        ) for runner_index in range(train_agent_count)]
        self.__minimum_random_action_probabilities = torch.logspace(
            torch.log(torch.tensor(random_action_probability)),
            torch.log(torch.tensor(minimum_random_action_probability)),
            train_agent_count + 1,
        ).unsqueeze(dim=-1)[1:]
        self.__random_action_probabilities = torch.ones_like(self.__minimum_random_action_probabilities)
        self.__buffer = Buffer(
            train_agent_count=train_agent_count,
            observation_length=observation_length,
            action_length=self.__action_length,
            buffer_size=buffer_size,
        )

    @property
    def state_dicts(self) -> tuple[tuple[dict[str, typing.Any], dict[str, typing.Any]], dict[str, typing.Any]]:
        return self.__critic.state_dicts, self.__actor.state_dict

    @property
    def random_action_probabilities(self) -> numpy.ndarray:
        return self.__random_action_probabilities.squeeze().cpu().numpy()

    @property
    def actor(self) -> Actor:
        return self.__actor

    def step(self) -> None:
        observations = torch.stack([torch.tensor(runner.observation) for runner in self.__runners])
        actor_actions = self.actor.forward_network(observations=observations)
        random_action_indexes = torch.rand_like(self.__random_action_probabilities) < self.__random_action_probabilities
        actions = actor_actions * ~random_action_indexes + torch.rand_like(actor_actions) * random_action_indexes
        runner_steps = [runner.step(action=action.squeeze()) for action, runner in zip(actions, self.__runners)]
        terminations = torch.tensor([dead for dead, reward in runner_steps])
        rewards = torch.tensor([reward for dead, reward in runner_steps])
        self.__buffer.push(observations=observations, actions=actions, rewards=rewards, terminations=terminations)
        self.__random_action_probabilities = torch.maximum(input=self.__random_action_probabilities
                                                                 * self.__random_action_probability_decay,
                                                           other=self.__minimum_random_action_probabilities)

    def close(self) -> None:
        for runner in self.__runners:
            runner.close()

    def train(self) -> tuple[float, float]:
        if not self.__buffer.ready:
            return 0, 0
        observations, actions, rewards, terminations, next_observations \
            = self.__buffer.random_observations(number=self.__train_batch_size)
        loss_1 = self.__critic.update(
            observation_actions=torch.concatenate((observations, actions), dim=-1),
            immediate_rewards=rewards.unsqueeze(dim=-1),
            terminations=terminations.unsqueeze(dim=-1),
            next_observations=next_observations,
            discount_factor=self.__discount_factor,
            noise_variance=self.__noise_variance,
            actor=self.__actor,
        )

        loss_2 = self.__actor.update(
            observations=observations,
            target_update_proportion=self.__target_update_proportion,
            critic=self.__critic,
        )

        return loss_1.__float__(), loss_2.__float__()
