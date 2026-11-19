"""Push-Pull, anti-entropy e orçamento."""

from copy import deepcopy
from functools import partial
from pathlib import Path

import numpy as np
import simpy
import yaml

from src.metrics import Metrics
from src.network import Network
from src.policies.budget import Budget
from src.policies.fanout import FixedFanout
from src.protocols import Message, Push, PushPull
from src.simulation import Node, Simulation

BASELINE = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "configs" / "baseline.yaml").read_text()
)
DATA, DIGEST = 272, 16  # tamanhos das mensagens, em bytes


def two_nodes(protocol_class=Push, versions=(0, 0)):
    """Rede de 2 nós com um protocolo. Com 2 nós, o peer sorteado é sempre o outro."""
    env = simpy.Environment()
    metrics = Metrics(env, 2)
    network = Network(env, 2, np.random.default_rng(0), metrics)
    protocol = protocol_class(
        network, np.random.default_rng(0), metrics, FixedFanout(1), payload_bytes=256
    )
    nodes = [Node(0), Node(1)]
    for node, version in zip(nodes, versions):
        node.version = version
        network.register(node.id, partial(protocol.on_message, node))
    return env, protocol, nodes, metrics


def run(**overrides):
    """Execução completa. Chaves `network`, `protocol` e `budget` sobrescrevem o baseline."""
    config = deepcopy(BASELINE)
    for section, values in overrides.items():
        config[section].update(values)
    return Simulation(config, seed=5).run()


# --- Push-Pull ------------------------------------------------------------


def test_pull_request_is_answered_with_the_update():
    env, protocol, (_, uninformed), metrics = two_nodes(PushPull, versions=(1, 0))
    protocol.on_round(uninformed)  # DIGEST de pedido
    env.run()
    assert uninformed.version == 1
    summary = metrics.summary()
    assert summary["bytes_control"] == DIGEST
    assert summary["bytes_repair"] == DATA
    assert summary["bytes_total"] == DIGEST + DATA


def test_pull_request_to_an_uninformed_peer_gets_no_reply():
    env, protocol, nodes, metrics = two_nodes(PushPull)
    protocol.on_round(nodes[0])
    env.run()
    assert metrics.summary()["bytes_total"] == DIGEST


def test_informed_node_in_push_pull_pushes_like_push():
    env, protocol, (informed, uninformed), metrics = two_nodes(PushPull, versions=(1, 0))
    protocol.on_round(informed)
    env.run()
    assert uninformed.version == 1
    summary = metrics.summary()
    assert (summary["bytes_total"], summary["bytes_repair"]) == (DATA, 0)


# --- Anti-entropy ---------------------------------------------------------


def test_anti_entropy_pulls_from_a_newer_peer():
    env, protocol, (initiator, _), metrics = two_nodes(versions=(0, 1))
    protocol.on_ae_round(initiator)
    env.run()
    assert initiator.version == 1 and initiator.ae_peer is None
    # DIGEST do iniciador + DATA de reparo do peer
    assert metrics.summary()["bytes_total"] == DIGEST + DATA
    assert metrics.summary()["bytes_repair"] == DATA


def test_anti_entropy_pushes_to_an_older_peer():
    env, protocol, (initiator, peer), metrics = two_nodes(versions=(1, 0))
    protocol.on_ae_round(initiator)
    env.run()
    assert peer.version == 1 and initiator.ae_peer is None
    # DIGEST do iniciador + DIGEST de resposta + DATA de reparo do iniciador
    summary = metrics.summary()
    assert summary["bytes_control"] == 2 * DIGEST
    assert summary["bytes_repair"] == DATA


def test_anti_entropy_between_equal_versions_costs_two_digests():
    env, protocol, (initiator, _), metrics = two_nodes(versions=(1, 1))
    protocol.on_ae_round(initiator)
    env.run()
    summary = metrics.summary()
    assert summary["bytes_total"] == summary["bytes_control"] == 2 * DIGEST
    assert summary["duplicates"] == 0 and initiator.ae_peer is None


def test_unanswered_exchange_counts_as_timeout_at_the_next_tick():
    env, protocol, (initiator, peer), metrics = two_nodes(versions=(1, 1))
    protocol.on_ae_round(initiator)  # respondida
    env.run()
    protocol.network.online[peer.id] = False
    protocol.on_ae_round(initiator)  # o peer está offline: sem resposta
    env.run()
    assert metrics.timeouts == 0  # o timeout só é contado no tick seguinte
    protocol.on_ae_round(initiator)
    assert metrics.timeouts == 1


def test_a_pushed_data_does_not_close_the_exchange():
    _, protocol, (initiator, peer), _ = two_nodes(versions=(1, 1))
    protocol.network.online[peer.id] = False
    protocol.on_ae_round(initiator)  # sem resposta
    protocol.on_message(initiator, peer.id, Message(version=1, size_bytes=DATA))
    assert initiator.ae_peer == peer.id


# --- Orçamento ------------------------------------------------------------


def test_budget_drops_what_does_not_fit_and_refills_each_window():
    env = simpy.Environment()
    metrics = Metrics(env, 2)
    budget = Budget(env, 2, bytes_per_interval=2 * DATA, interval_ms=1000)
    network = Network(env, 2, np.random.default_rng(0), metrics, budget=budget)
    network.register(1, lambda src, message: None)
    message = Message(version=1, size_bytes=DATA)

    assert [network.send(0, 1, message) for _ in range(3)] == [True, True, False]
    env.run(until=999)
    assert network.send(0, 1, message) is False  # mesma janela
    env.run(until=1000)
    assert network.send(0, 1, message) is True  # janela nova
    assert metrics.budget_drops == 2
    assert metrics.summary()["bytes_total"] == 3 * DATA  # a barrada não conta


def test_budget_dropped_digest_does_not_open_an_exchange():
    env, protocol, (initiator, _), metrics = two_nodes(versions=(1, 1))
    protocol.network.budget = Budget(env, 2, bytes_per_interval=0, interval_ms=1000)
    protocol.on_ae_round(initiator)
    protocol.on_ae_round(initiator)
    assert (metrics.budget_drops, metrics.timeouts) == (2, 0)


# --- Simulação completa ---------------------------------------------------


def test_push_pull_covers_the_network_with_control_and_repair_bytes():
    summary = run(protocol={"name": "push_pull"})
    assert summary["coverage_final"] == 1.0
    assert summary["bytes_control"] > 0 and summary["bytes_repair"] > 0
    assert summary["timeouts"] == 0  # Push-Pull não gera timeouts


def test_anti_entropy_alone_disseminates_the_update():
    # fanout 0 desliga o Push: toda DATA é reparo de anti-entropy
    summary = run(protocol={"fanout": 0, "ae_interval_ms": 1000})
    assert summary["coverage_final"] == 1.0
    assert summary["bytes_repair"] == summary["bytes_total"] - summary["bytes_control"]
    assert summary["timeouts"] == 0  # rede estável: toda troca tem resposta


def test_anti_entropy_times_out_under_churn():
    summary = run(protocol={"ae_interval_ms": 1000}, network={"churn_fraction": 0.2})
    assert summary["timeouts"] > 0


def test_budget_caps_the_bytes_of_every_node():
    limit = 2 * DATA  # por nó, a cada 1.000 ms; fanout 5 pede 10 DATA por janela
    summary = run(protocol={"fanout": 5}, budget={"bytes_per_node_per_interval": limit})
    assert summary["budget_drops"] > 0
    assert summary["bytes_total"] <= 100 * 60 * limit  # nós × janelas × teto
    assert summary["coverage_final"] == 1.0
