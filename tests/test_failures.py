import math
from copy import deepcopy
from pathlib import Path

import numpy as np
import simpy
import yaml

from src.metrics import Metrics
from src.network import Network, random_regular_neighbors
from src.protocols import Message
from src.simulation import Simulation

BASELINE = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "configs" / "baseline.yaml").read_text()
)
MESSAGE = Message(version=1, size_bytes=272)


def make_network(n=4, **kwargs):
    """Rede de teste. Devolve (env, rede, métricas, lista de entregas)."""
    env = simpy.Environment()
    metrics = Metrics(env, n)
    network = Network(env, n, np.random.default_rng(0), metrics, **kwargs)
    delivered = []
    for node_id in range(n):
        network.register(node_id, lambda src, message, dst=node_id: delivered.append(dst))
    return env, network, metrics, delivered


def config_with(**network):
    config = deepcopy(BASELINE)
    config["network"].update(network)
    return config


# --- Transporte ---------------------------------------------------------


def test_total_loss_delivers_nothing_but_counts_the_bytes():
    env, network, metrics, delivered = make_network(
        packet_loss=1.0, loss_rng=np.random.default_rng(1)
    )
    for _ in range(50):
        network.send(0, 1, MESSAGE)
    env.run()
    assert delivered == []
    assert metrics.summary()["bytes_total"] == 50 * 272


def test_partial_loss_drops_about_the_configured_fraction():
    env, network, _, delivered = make_network(
        packet_loss=0.3, loss_rng=np.random.default_rng(1)
    )
    for _ in range(2000):
        network.send(0, 1, MESSAGE)
    env.run()
    assert 0.66 < len(delivered) / 2000 < 0.74  # esperado: 0,70


def test_offline_state_is_checked_at_delivery_time():
    env, network, _, delivered = make_network()
    network.send(0, 1, MESSAGE)  # o destinatário fica offline com a mensagem em trânsito
    network.send(0, 2, MESSAGE)  # o remetente fica offline depois do envio
    network.online[1] = False
    network.online[0] = False
    env.run()
    assert delivered == [2]


def test_partition_blocks_only_messages_between_groups():
    env, network, _, delivered = make_network()
    network.send(0, 1, MESSAGE)  # grupos 0 e 1: bloqueada
    network.send(0, 2, MESSAGE)  # mesmo grupo (pares): entregue
    network.partition_groups = 2  # começa com as mensagens em trânsito
    env.run()
    assert delivered == [2]

    network.partition_groups = 0  # reconexão
    network.send(0, 1, MESSAGE)
    env.run()
    assert delivered == [2, 1]


def test_regular_topology_is_symmetric_and_sampling_stays_inside_it():
    neighbors = random_regular_neighbors(50, 8, np.random.default_rng(3))
    assert neighbors.shape == (50, 8)
    for node, row in enumerate(neighbors):
        assert len(set(row)) == 8 and node not in row
        assert all(node in neighbors[peer] for peer in row)  # arestas nos dois sentidos
    same = random_regular_neighbors(50, 8, np.random.default_rng(3))
    assert (neighbors == same).all()  # mesma seed, mesma topologia

    _, network, _, _ = make_network(n=50, neighbors=neighbors)
    rng = np.random.default_rng(0)
    for _ in range(200):
        peers = network.sample_peers(7, 3, rng)
        assert len(set(peers)) == 3 and set(peers) <= set(neighbors[7])


# --- Simulação completa ---------------------------------------------------


def offline_sets(simulation, until_ms=20_000):
    """Conjunto de nós offline no meio de cada período de churn."""
    sets = []
    for t in range(2_500, until_ms, 5_000):
        simulation.env.run(until=t)
        sets.append({i for i, up in enumerate(simulation.network.online) if not up})
    return sets


def test_churn_keeps_the_configured_fraction_offline_and_spares_the_origin():
    simulation = Simulation(config_with(churn_fraction=0.2), seed=5)
    origin = next(node.id for node in simulation.nodes if node.version > 0)
    sets = offline_sets(simulation)
    assert all(len(offline) == 20 and origin not in offline for offline in sets)
    assert len({frozenset(offline) for offline in sets}) > 1  # o conjunto muda


def test_churn_schedule_does_not_depend_on_the_protocol():
    def schedule(fanout):
        config = config_with(churn_fraction=0.1)
        config["protocol"]["fanout"] = fanout
        return offline_sets(Simulation(config, seed=5))

    assert schedule(1) == schedule(3)


def test_coverage_under_churn_counts_only_online_nodes():
    simulation = Simulation(config_with(churn_fraction=0.2), seed=5)
    summary = simulation.run()
    assert simulation.metrics.cohort == 80
    online_informed = sum(
        node.version > 0 and simulation.network.online[node.id]
        for node in simulation.nodes
    )
    assert simulation.metrics.informed == online_informed
    assert all(0 <= coverage <= 1 for _, coverage in simulation.metrics.coverage_events)
    assert summary["t95_ms"] > 0 and math.isnan(summary["recovery_ms"])


def test_partition_confines_the_update_until_reconnection():
    partition = {"groups": 2, "start_ms": 0, "end_ms": 20_000}
    simulation = Simulation(config_with(partition=partition), seed=5)
    origin = next(node.id for node in simulation.nodes if node.version > 0)

    simulation.env.run(until=20_000)  # ainda particionada
    informed = [node.id for node in simulation.nodes if node.version > 0]
    assert len(informed) == 50  # o grupo da origem inteiro, e só ele
    assert all(node_id % 2 == origin % 2 for node_id in informed)

    summary = simulation.run()
    assert summary["coverage_final"] == 1.0
    assert summary["recovery_ms"] == summary["t95_ms"] - 20_000 > 0


def test_total_loss_stops_the_dissemination():
    summary = Simulation(config_with(packet_loss=1.0), seed=5).run()
    assert summary["coverage_final"] == 0.01
    assert math.isnan(summary["t95_ms"])


def test_push_covers_a_regular_topology():
    config = config_with(nodes=50, topology="random_regular_connected")
    summary = Simulation(config, seed=5).run()
    assert summary["coverage_final"] == 1.0
