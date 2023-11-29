import torch
import torch.nn as nn
import torch.optim as optim
import gym
import numpy as np
import matplotlib.pyplot as plt

class QNetwork(nn.Module):
    def __init__(self, input_size, output_size):
        super(QNetwork, self).__init__()
        self.fc1 = nn.Linear(input_size, 128)
        self.relu1 = nn.ReLU()
        # self.fc2 = nn.Linear(128, 128)
        # self.relu2 = nn.ReLU()
        self.output_layer = nn.Linear(128, output_size)

    def forward(self, state):
        x = self.fc1(state)
        x = self.relu1(x)
        # x = self.fc2(x)
        # x = self.relu2(x)
        q_values = self.output_layer(x)
        return q_values


# Define the DQN Agent
class DQNAgent:
    def __init__(self, state_size, action_size, theta, feature_matrix, one_feature, learning_rate=0.001, gamma=0.99):
        self.q_network = QNetwork(state_size, action_size)
        self.target_q_network = QNetwork(state_size, action_size)
        self.target_q_network.load_state_dict(self.q_network.state_dict())
        self.optimizer = optim.Adam(self.q_network.parameters(), lr=learning_rate)
        self.gamma = gamma

        self.theta_learning_rate = 0.05
        self.theta = theta
        self.feature_matrix = feature_matrix
        self.one_feature = one_feature

    def select_action(self, state, epsilon):
        if np.random.rand() < epsilon:
            return np.random.choice(3)
        else:
            with torch.no_grad():
                q_values = self.q_network(torch.FloatTensor(state))
                return torch.argmax(q_values).item()

    def update_q_network(self, state, action, reward, next_state, done):
        state = torch.FloatTensor(state)
        next_state = torch.FloatTensor(next_state)
        q_values = self.q_network(state)
        next_q_values = self.target_q_network(next_state)

        target = q_values.clone()
        if not done:
            target[action] = reward + self.gamma * torch.max(next_q_values).item()
        else:
            target[action] = reward

        loss = nn.MSELoss()(q_values, target.detach())
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

    def update_target_network(self):
        self.target_q_network.load_state_dict(self.q_network.state_dict())

    def state_to_idx(self, env, state):
        """
        Converts state (pos, vel) to the integer value using the mountain car environment.
        :param state:
        :return:
        """
        """ """
        env_low = env.observation_space.low
        env_high = env.observation_space.high
        env_distance = (env_high - env_low) / self.one_feature
        position_idx = int((state[0] - env_low[0]) / env_distance[0])
        velocity_idx = int((state[1] - env_low[1]) / env_distance[1])
        state_idx = position_idx + velocity_idx * self.one_feature
        return state_idx

    def discretize_state(self, env, state):
        env_low = env.observation_space.low
        env_high = env.observation_space.high
        env_distance = (env_high - env_low) / self.one_feature
        position_idx = int((state[0] - env_low[0]) / env_distance[0])
        velocity_idx = int((state[1] - env_low[1]) / env_distance[1])
        return [position_idx, velocity_idx]

    def get_demonstrations(self, env):
        """
        Parses the demonstrations and returns the demonstrations.
        :param one_feature:
        :return:
        """
        env_low = env.observation_space.low
        env_high = env.observation_space.high
        env_distance = (env_high - env_low) / self.one_feature

        raw_demo = np.load(file="../expert_demo/expert_demo.npy")
        demonstrations = np.zeros((len(raw_demo), len(raw_demo[0]), 3))
        for x in range(len(raw_demo)):
            for y in range(len(raw_demo[0])):
                position_idx = int((raw_demo[x][y][0] - env_low[0]) / env_distance[0])
                velocity_idx = int((raw_demo[x][y][1] - env_low[1]) / env_distance[1])
                state_idx = position_idx + velocity_idx * self.one_feature
                demonstrations[x][y][0] = state_idx
                demonstrations[x][y][1] = raw_demo[x][y][2]
        return demonstrations

    def expert_feature_expectations(self, demonstrations):
        feature_expectations = np.zeros(self.feature_matrix.shape[0])

        for demonstration in demonstrations:
            for state_idx, _, _ in demonstration:
                feature_expectations += self.feature_matrix[int(state_idx)]

        feature_expectations /= demonstrations.shape[0]
        return feature_expectations

    def get_reward(self, n_states, state_idx):
        """
        Returns the achieved reward.
        :param n_states:
        :param state_idx:
        :return:
        """
        irl_rewards = self.feature_matrix.dot(self.theta).reshape((n_states,))
        return irl_rewards[state_idx]

    def maxent_irl(self, expert, learner):
        """
        Max Entropy Learning step.
        :param expert:
        :param learner:
        :param learning_rate:
        :return:
        """
        gradient = expert - learner
        self.theta += self.theta_learning_rate * gradient

        print("Theta", self.theta)

        # Clip theta
        for j in range(len(self.theta)):
            if self.theta[j] > 0: # log values
                self.theta[j] = 0


# Training Loop
def train(agent, env, expert, learner_feature_expectations, n_states, episodes=30000, max_steps=10000, epsilon_start=1.0,
          epsilon_decay=0.995, epsilon_min=0.01):
    epsilon = epsilon_start
    episode_arr, scores = [], []

    for episode in range(episodes):
        state, info = env.reset()
        total_reward = 0

        # Mini-Batches:
        if (episode != 0 and episode == 10000) or (episode > 10000 and episode % 5000 == 0):
            # calculate density
            learner = learner_feature_expectations / episode
            # Maximum Entropy IRL step
            agent.maxent_irl(expert, learner)

        for step in range(max_steps):
            action = agent.select_action(state, epsilon)

            next_state, reward, done, _, _ = env.step(action)
            # Real Reward
            total_reward += reward

            # IRL
            state_idx = agent.state_to_idx(env, state)
            irl_reward = agent.get_reward(n_states, state_idx)

            agent.update_q_network(state, action, irl_reward, next_state, done)
            agent.update_target_network()

            # State counting for densitiy
            learner_feature_expectations += agent.feature_matrix[int(state_idx)]

            state = next_state
            if done:
                break

        scores.append(total_reward)
        episode_arr.append(episode)
        epsilon = max(epsilon * epsilon_decay, epsilon_min)
        print(f"Episode: {episode + 1}, Total Reward: {total_reward}, Epsilon: {epsilon}")

        if episode % 1000 == 0 and episode != 0:
            score_avg = np.mean(scores)
            print('{} episode average score is {:.2f}'.format(episode, score_avg))
            plt.plot(episode_arr, scores, 'b')
            plt.savefig(f"../learning_curves/maxent_{episodes}_{episode}_qnetwork.png")
            learner = learner_feature_expectations / episode
            plt.imshow(learner.reshape((20, 20)), cmap='viridis', interpolation='nearest')
            plt.savefig(f"../heatmap/learner_{episode}_deep.png")
            plt.imshow(theta.reshape((20, 20)), cmap='viridis', interpolation='nearest')
            plt.savefig(f"../heatmap/theta_{episode}_deep.png")
            plt.imshow(feature_matrix.dot(theta).reshape((20, 20)), cmap='viridis', interpolation='nearest')
            plt.savefig(f"../heatmap/rewards_{episode}_deep.png")

            torch.save(agent.q_network.state_dict(), f"../results/maxent_{episodes}_{episode}_network_main.pth")

        if episode == episodes - 1:
            plt.plot(episode_arr, scores, 'b')
            plt.savefig(f"../learning_curves/maxentdeep_{episodes}_qdeep_main.png")

    torch.save(agent.q_network.state_dict(), f"../results/maxentdeep_{episodes}_q_network_main.pth")


# Main function
if __name__ == "__main__":
    env = gym.make('MountainCar-v0')
    state_size = env.observation_space.shape[0]
    action_size = 3  # env.action_space.n

    # Feature Matrix
    n_states = 400  # 20 * 20
    one_feature = 20  # number of state per one feature
    feature_matrix = np.eye(n_states)

    # Theta works as Rewards
    theta_learning_rate = 0.01
    theta = -(np.random.uniform(size=(n_states,)))

    agent = DQNAgent(state_size, action_size, theta, feature_matrix, one_feature)

    demonstrations = agent.get_demonstrations(env)
    expert = agent.expert_feature_expectations(demonstrations)
    learner_feature_expectations = np.zeros(n_states)

    train(agent, env, expert, learner_feature_expectations, n_states)