import math
from copy import deepcopy
from pathlib import Path
from statistics import mean
from types import SimpleNamespace

import pytest
import yaml

from src.metrics import Metrics
from src.simulation import Simulation

BASELINE = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "configs" / "baseline.yaml").read_text()
)


def test_metrics_from_a_hand_written_timeline():
    clock = SimpleNamespace(now=0)  # relógio falso: o teste escolhe o instante
    metrics = Metrics(clock, n_nodes=4)

    metrics.on_informed()  # t=0: o nó de origem, cobertura 1/4
    clock.now = 500
    metrics.on_send(272)
    clock.now = 510
    metrics.on_informed()  # cobertura 2/4: cruza 50%
    clock.now = 1000
    metrics.on_send(272)
    metrics.on_send(272)
    clock.now = 1010
    metrics.on_informed()  # cobertura 3/4: ainda abaixo de 95%
    metrics.on_duplicate()
    clock.now = 1500
    metrics.on_send(272)
    clock.now = 1510
    metrics.on_informed()  # cobertura 4/4: cruza 95%
    clock.now = 2000
    metrics.on_send(272)  # enviado depois de T95

    assert metrics.summary() == {
        "coverage_final": 1.0,
        "t50_ms": 510,
        "t95_ms": 1510,
        "bytes_total": 5 * 272,
        "bytes_until_t95": 4 * 272,
        "bytes_control": 0,
        "bytes_repair": 0,
        "duplicates": 1,
        "timeouts": 0,
        "budget_drops": 0,
    }
    assert metrics.coverage_curve(step_ms=500) == [
        (0, 0.25),
        (500, 0.25),
        (1000, 0.5),
        (1500, 0.75),
        (2000, 1.0),
    ]


def test_t95_and_bytes_until_t95_are_nan_when_95_percent_is_not_reached():
    clock = SimpleNamespace(now=0)
    metrics = Metrics(clock, n_nodes=4)
    metrics.on_informed()
    metrics.on_informed()
    metrics.on_send(272)

    summary = metrics.summary()
    assert summary["coverage_final"] == 0.5
    assert summary["t50_ms"] == 0
    assert math.isnan(summary["t95_ms"]) and math.isnan(summary["bytes_until_t95"])
    assert summary["bytes_total"] == 272


def test_summary_of_a_push_run_is_consistent():
    config = deepcopy(BASELINE)
    simulation = Simulation(config, seed=1)
    summary = simulation.run()

    assert summary["coverage_final"] == 1.0
    assert summary["t50_ms"] < summary["t95_ms"]
    # rodadas em múltiplos de 500 ms, entrega 10 ms depois
    assert summary["t95_ms"] % 500 == 10
    assert summary["duplicates"] == sum(node.duplicates for node in simulation.nodes)
    # sem perda, toda mensagem informa um nó (99 vezes) ou é duplicata
    assert summary["bytes_total"] == 272 * (99 + summary["duplicates"])
    assert 0 < summary["bytes_until_t95"] < summary["bytes_total"]


@pytest.mark.parametrize("fanout", [1, 3])
def test_mean_coverage_follows_the_analytic_push_model(fanout):
    """Validação da página 3 do PDF: rede completa, sem falhas, N=100."""
    n, rounds, seeds = 100, 12, range(30)
    config = deepcopy(BASELINE)
    config["protocol"]["fanout"] = fanout
    config["simulation"]["duration_ms"] = rounds * 500 + 11  # inclui a última entrega

    curves = []
    for seed in seeds:
        simulation = Simulation(config, seed)
        simulation.run()
        events = simulation.metrics.coverage_events
        # cobertura logo após as entregas da rodada k, em t = k * 500 + 10
        curves.append(
            [max(c for t, c in events if t <= k * 500 + 10) for k in range(rounds + 1)]
        )

    informed, analytic = 1.0, [1 / n]
    for _ in range(rounds):
        informed += (n - informed) * (1 - (1 - fanout / (n - 1)) ** informed)
        analytic.append(informed / n)

    simulated = [mean(curve[k] for curve in curves) for k in range(rounds + 1)]
    # medido com 30 seeds: 0,007 (fanout 1) e 0,006 (fanout 3); 0,02 dá folga
    assert max(abs(s - a) for s, a in zip(simulated, analytic)) < 0.02
