from copy import deepcopy
from pathlib import Path

import simpy
import yaml

from src.metrics import Metrics
from src.policies.fanout import FixedFanout
from src.protocols import Message, Push
from src.simulation import Node, Simulation

BASELINE = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "configs" / "baseline.yaml").read_text()
)


def run(seed, fanout=1, duration_ms=None):
    config = deepcopy(BASELINE)
    config["protocol"]["fanout"] = fanout
    if duration_ms is not None:
        config["simulation"]["duration_ms"] = duration_ms
    simulation = Simulation(config, seed)
    simulation.run()
    return simulation


def infected(simulation):
    return sum(node.version > 0 for node in simulation.nodes)


def test_push_reaches_every_node():
    assert infected(run(seed=1)) == 100


def test_infected_count_at_most_doubles_per_round_with_fanout_1():
    # rodadas em t=500, 1000 e 1500, entregas 10 ms depois. até t=1600 são
    # 3 rodadas completas: no mínimo 2 infectados, no máximo 2**3
    simulation = run(seed=1, duration_ms=1600)
    assert 2 <= infected(simulation) <= 8


def test_same_seed_gives_same_run():
    def duplicates(seed):
        return [node.duplicates for node in run(seed, duration_ms=5000).nodes]

    assert duplicates(3) == duplicates(3)
    assert duplicates(3) != duplicates(4)


def test_on_message_adopts_newer_version_and_counts_duplicates():
    metrics = Metrics(simpy.Environment(), n_nodes=2)
    push = Push(None, None, metrics, FixedFanout(1), payload_bytes=256)
    node = Node(0)
    message = Message(version=1, size_bytes=272)
    push.on_message(node, src=1, message=message)
    assert (node.version, node.duplicates) == (1, 0)
    push.on_message(node, src=2, message=message)
    assert (node.version, node.duplicates) == (1, 1)
    assert (metrics.informed, metrics.duplicates) == (1, 1)
