import numpy as np
import simpy

from src.metrics import Metrics
from src.network import Network
from src.protocols import Message

MESSAGE = Message(version=1, size_bytes=272)


def arrival_times(seed, latency_ms, n_messages=200):
    """Envia `n_messages` do nó 0 ao nó 1 e devolve os instantes de chegada."""
    env = simpy.Environment()
    network = Network(env, 2, np.random.default_rng(seed), Metrics(env, 2), latency_ms)
    times = []
    network.register(1, lambda src, message: times.append(env.now))
    for _ in range(n_messages):
        network.send(0, 1, MESSAGE)
    env.run()
    return times


def test_message_arrives_exactly_after_latency():
    env = simpy.Environment()
    metrics = Metrics(env, 3)
    network = Network(env, 3, np.random.default_rng(0), metrics)
    received = []
    network.register(1, lambda src, message: received.append((env.now, src, message)))

    network.send(0, 1, MESSAGE)
    assert received == []  # send só agenda; nada é entregue no envio
    assert metrics.summary()["bytes_total"] == 272  # os bytes contam no envio

    env.run(until=10)  # executa os eventos anteriores a t=10
    assert received == []

    env.run()  # executa até a fila de eventos esvaziar
    assert received == [(10, 0, MESSAGE)]


def test_latency_stays_in_range_and_is_reproducible():
    times = arrival_times(seed=7, latency_ms=(10, 200))
    assert min(times) >= 10 and max(times) <= 200
    assert len(set(times)) > 1  # a latência varia entre mensagens
    assert times == arrival_times(seed=7, latency_ms=(10, 200))
    assert times != arrival_times(seed=8, latency_ms=(10, 200))


def test_sample_peers_returns_distinct_peers_and_never_the_node_itself():
    network = Network(simpy.Environment(), 5, rng=None, metrics=None)
    rng = np.random.default_rng(0)
    seen = set()
    for _ in range(200):
        peers = network.sample_peers(2, 3, rng)
        assert len(set(peers)) == 3 and 2 not in peers
        seen.update(peers)
    assert seen == {0, 1, 3, 4}  # todo outro nó pode ser sorteado
    # Pedir mais peers do que existem devolve todos os outros nós.
    assert sorted(network.sample_peers(2, 10, rng)) == [0, 1, 3, 4]
