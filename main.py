import itertools
import pathlib

import gymnasium
import numpy
import torch.cuda

from agents.actor_critic.actor import Actor
from agents.basic_agent import BasicAgent
from agents.super_agent import SuperAgent
from agents.runner import Runner
import matplotlib.pyplot
import tqdm


def validation_run(
        load_path: pathlib.Path,
        observation_length: int,
        action_length: int,
        nn_width: int,
        runner: Runner,
) -> None:
    actor = Actor(load_path=load_path,
                  observation_length=observation_length,
                  action_length=action_length,
                  nn_width=nn_width)
    try:
        while True:
            print(runner.run_full(actor=actor))
    except KeyboardInterrupt:
        return


def train_run(
        agent_count: int,
        validation_interval: int,
        validation_repeats: int,
        save_path: pathlib.Path,
        actor_nn_width: int,
        critic_nn_width: int,
        discount_factor: float,
        train_batch_size: int,
        buffer_size: int,
        random_action_probability: float,
        minimum_random_action_probability: float,
        random_action_probability_decay: float,
        observation_length: int,
        action_length: int,
        environment: str,
        seed: int,
        target_update_proportion: float,
        validation_runner: Runner,
) -> None:
    super_agent = SuperAgent(train_agent_count=agent_count,
                             save_path=save_path,
                             environment=environment,
                             seed=seed,
                             actor_nn_width=actor_nn_width,
                             critic_nn_width=critic_nn_width,
                             discount_factor=discount_factor,
                             train_batch_size=train_batch_size,
                             buffer_size=buffer_size,
                             random_action_probability=random_action_probability,
                             minimum_random_action_probability=minimum_random_action_probability,
                             random_action_probability_decay=random_action_probability_decay,
                             observation_length=observation_length,
                             action_length=action_length,
                             target_update_proportion=target_update_proportion,
                             )
    best_state_dicts = super_agent.state_dicts
    figure = matplotlib.pyplot.figure()
    loss_subplot = figure.add_subplot(2, 2, 1)
    losses = []
    action_loss_subplot = figure.add_subplot(2, 2, 2)
    action_losses = []
    survival_times_subplot = figure.add_subplot(2, 2, 3)
    survival_times = []
    random_probability_subplot = figure.add_subplot(2, 2, 4)
    random_probabilities = []
    figure.show()
    try:
        for iteration in tqdm.tqdm(itertools.count()):
            if iteration % validation_interval == 0:
                loss_subplot.plot(losses)
                action_loss_subplot.plot(action_losses)
                survival_times.append(numpy.mean([validation_runner.run_full(super_agent.actor)
                                                  for _ in range(validation_repeats)]))
                survival_times_subplot.plot(survival_times)
                random_probabilities.append(super_agent.random_action_probabilities)
                random_probability_subplot.plot(random_probabilities)
                figure.canvas.draw()
                figure.canvas.flush_events()
                if len(survival_times) < 2 or survival_times[-1] >= max(survival_times[:-1]):
                    best_state_dicts = super_agent.state_dicts
            super_agent.step()
            q_loss, action_loss = super_agent.train()
            losses.append(q_loss)
            action_losses.append(action_loss)
    except KeyboardInterrupt:
        super_agent.close()
        torch.save(best_state_dicts[0][0], save_path / "q1")
        torch.save(best_state_dicts[0][1], save_path / "q2")
        torch.save(best_state_dicts[1], save_path / "action")
        print("models saved")


def run(train: bool,
        agent_count: int,
        validation_interval: int,
        validation_repeats: int,
        save_path: pathlib.Path,
        actor_nn_width: int,
        critic_nn_width: int,
        discount_factor: float,
        train_batch_size: int,
        buffer_size: int,
        random_action_probability: float,
        minimum_random_action_probability: float,
        random_action_probability_decay: float,
        observation_length: int,
        action_length: int,
        environment: str,
        seed: int,
        target_update_proportion: float) -> None:
    torch.set_default_device('cuda')
    validation_runner = Runner(
        env=gymnasium.make(environment, render_mode=None if train else "human"),
        agent=BasicAgent(),
        seed=seed,
    )
    if train:
        train_run(
            agent_count=agent_count,
            validation_interval=validation_interval,
            validation_repeats=validation_repeats,
            save_path=save_path,
            actor_nn_width=actor_nn_width,
            critic_nn_width=critic_nn_width,
            discount_factor=discount_factor,
            train_batch_size=train_batch_size,
            buffer_size=buffer_size,
            random_action_probability=random_action_probability,
            minimum_random_action_probability=minimum_random_action_probability,
            random_action_probability_decay=random_action_probability_decay,
            observation_length=observation_length,
            action_length=action_length,
            environment=environment,
            seed=seed + 1,
            target_update_proportion=target_update_proportion,
            validation_runner=validation_runner,
        )
    else:
        validation_run(
            load_path=save_path,
            observation_length=observation_length,
            action_length=action_length,
            nn_width=actor_nn_width,
            runner=validation_runner,
        )
    validation_runner.close()


def main(selection: str, train: bool) -> None:
    model_root = pathlib.Path("models")
    random_action_probability = 1
    minimum_random_action_probability = 0.1
    seed = 42
    match selection:
        case 'cartpole':
            environment = "CartPole-v1"
            observation_length = 4
            action_length = 1
            validation_interval = 100
            validation_repeats = 100
            buffer_size = 2 ** 8
            #
            discount_factor = 0.9
            agent_count = 2 ** 7
            random_action_probability_decay = 1 - 1 / 2 ** 10
            train_batch_size = 2 ** 6
            actor_nn_width = 2 ** 4
            critic_nn_width = 2 ** 4
            target_update_proportion = 2 ** 0
        case 'bipedal':
            agent_count = 2 ** 5
            validation_interval = 1000
            validation_repeats = 10
            actor_nn_width = 2 ** 9
            critic_nn_width = 2 ** 9
            discount_factor = 0.9
            train_batch_size = 2 ** 4
            buffer_size = 2 ** 15
            random_action_probability_decay = 1 - 1 / 2 ** 10
            environment = "BipedalWalker-v3"
            observation_length = 24
            action_length = 4
            target_update_proportion = 2 ** -1
        case _:
            raise NotImplementedError
    if not model_root.exists():
        model_root.mkdir()
    full_model_path = model_root / environment
    if not full_model_path.exists():
        full_model_path.mkdir()
    run(train=train,
        agent_count=agent_count,
        validation_interval=validation_interval,
        validation_repeats=validation_repeats,
        save_path=full_model_path,
        actor_nn_width=actor_nn_width,
        critic_nn_width=critic_nn_width,
        discount_factor=discount_factor,
        train_batch_size=train_batch_size,
        buffer_size=buffer_size,
        random_action_probability=random_action_probability,
        minimum_random_action_probability=minimum_random_action_probability,
        random_action_probability_decay=random_action_probability_decay,
        environment=environment,
        seed=seed,
        observation_length=observation_length,
        action_length=action_length,
        target_update_proportion=target_update_proportion)


if __name__ == '__main__':
    main(selection='cartpole', train=True)
