"""Fanout adaptativo e quiescência."""

from copy import deepcopy
from pathlib import Path

import yaml

from src.policies.fanout import AdaptiveFanout
from src.simulation import Node, Simulation

BASELINE = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "configs" / "baseline.yaml").read_text()
)
ADAPTIVE = {
    "min_fanout": 1,
    "max_fanout": 4,
    "duplicate_threshold": 0.5,
    "timeout_threshold": 0.3,
}


def policy_and_node(**overrides):
    node = Node(0)
    node.version = 1
    return AdaptiveFanout(1, **{**ADAPTIVE, **overrides}), node


def receive(node, new=0, duplicates=0):
    """Simula as DATA recebidas pelo nó desde a rodada anterior."""
    node.received += new + duplicates
    node.duplicates += duplicates


def run(adaptive, **network):
    config = deepcopy(BASELINE)
    config["network"].update(topology="random_regular_connected", **network)
    config["protocol"].update(ae_interval_ms=1000, adaptive={**ADAPTIVE, **adaptive})
    simulation = Simulation(config, seed=5)
    return simulation, simulation.run()


# --- Fanout adaptativo -----------------------------------------------------


def test_fanout_starts_at_the_maximum_and_falls_with_duplicates():
    policy, node = policy_and_node()
    assert policy.fanout(node) == 4  # rodada sem DATA recebida: nada muda
    receive(node, new=1, duplicates=1)  # fração 0,5: não passa do limiar
    assert policy.fanout(node) == 4
    fanouts = []
    for _ in range(5):
        receive(node, duplicates=2)  # fração 1,0
        fanouts.append(policy.fanout(node))
    assert fanouts == [3, 2, 1, 1, 1]  # para no mínimo


def test_fanout_rises_with_anti_entropy_timeouts():
    policy, node = policy_and_node()
    for _ in range(3):
        receive(node, duplicates=1)
        policy.fanout(node)
    assert policy.current[0] == 1
    policy.on_ae_result(node, "same")  # janela: 0 de 1
    assert policy.current[0] == 1
    policy.on_ae_result(node, "timeout")  # 1 de 2 = 0,5 > 0,3
    policy.on_ae_result(node, "timeout")  # 2 de 3
    assert policy.current[0] == 3
    for _ in range(5):
        policy.on_ae_result(node, "timeout")
    assert policy.current[0] == 4  # para no máximo
    for _ in range(5):  # a janela guarda só as 5 últimas trocas
        policy.on_ae_result(node, "same")
    assert not any(policy.ae_timeouts[0])


# --- Quiescência -----------------------------------------------------------


def test_node_goes_quiescent_after_enough_rounds_with_evidence():
    policy, node = policy_and_node(quiescence_rounds=3)
    receive(node, duplicates=1)
    assert policy.fanout(node) > 0  # contador 1
    assert policy.fanout(node) > 0  # rodada sem evidência: o contador não muda
    policy.on_ae_result(node, "same")
    assert policy.fanout(node) > 0  # contador 2, pela anti-entropy
    policy.on_ae_result(node, "timeout")  # timeout não é evidência
    assert policy.fanout(node) > 0
    receive(node, duplicates=1)
    assert policy.fanout(node) == 0  # contador 3: quiescente
    assert policy.fanout(node) == 0  # continua quiescente sem evidência nova


def test_quiescent_node_resumes_on_older_peer_or_newer_version():
    for resume in (
        lambda policy, node: policy.on_ae_result(node, "older"),
        lambda policy, node: policy.on_newer_version(node),
    ):
        policy, node = policy_and_node(quiescence_rounds=1)
        receive(node, duplicates=1)
        assert policy.fanout(node) == 0
        resume(policy, node)
        assert policy.fanout(node) > 0


def test_without_quiescence_the_fanout_never_reaches_zero():
    policy, node = policy_and_node()
    for _ in range(20):
        receive(node, duplicates=3)
        policy.on_ae_result(node, "same")
        assert policy.fanout(node) == max(1, policy.current[0])


# --- Simulação completa ----------------------------------------------------


def test_adaptive_fanout_covers_the_network_and_ends_at_the_minimum():
    simulation, summary = run({})
    assert summary["coverage_final"] == 1.0
    # estável e saturada: só chegam duplicatas e não há timeout que suba o fanout
    assert set(simulation.protocol.policy.current) == {1}


def test_quiescence_removes_traffic_after_saturation():
    _, active = run({})
    simulation, quiescent = run({"quiescence_rounds": 3})
    assert quiescent["coverage_final"] == 1.0
    assert quiescent["bytes_total"] < 0.5 * active["bytes_total"]
    policy = simulation.protocol.policy
    assert all(count >= 3 for count in policy.saturation_count)  # todos quiescentes


def test_quiescent_nodes_recover_the_other_group_after_a_partition():
    partition = {"groups": 2, "start_ms": 0, "end_ms": 20_000}
    _, summary = run({"quiescence_rounds": 3}, partition=partition)
    assert summary["coverage_final"] == 1.0
    assert summary["recovery_ms"] > 0
