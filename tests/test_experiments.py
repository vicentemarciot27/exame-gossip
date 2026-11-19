"""Helper do notebook e regras do tuning (experiments/)."""

import sys
from pathlib import Path

import optuna
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

import helper
import tuning

ADAPTIVE = {
    "min_fanout": 1,
    "max_fanout": 4,
    "duplicate_threshold": 0.5,
    "timeout_threshold": 0.3,
    "ae_interval_ms": 1000,
}
TUNED = {
    "push_tuned": {"fanout": 2, "gossip_interval_ms": 250},
    "push_pull": {"fanout": 1, "gossip_interval_ms": 500},
    "push_ae": {"fanout": 1, "gossip_interval_ms": 500, "ae_interval_ms": 2000},
    "adaptive_ae": ADAPTIVE,
    "adaptive_ae_quiescent": {**ADAPTIVE, "quiescence_rounds": 3},
}
SUMMARY_COLUMNS = [
    "run_id", "scenario", "protocol_variant", "seed", "n_nodes", "coverage_final",
    "t50_ms", "t95_ms", "bytes_total", "bytes_until_t95", "bytes_control",
    "bytes_repair", "duplicates", "timeouts", "budget_drops", "recovery_ms",
    "wall_time_s",
]  # fmt: skip


def small_plan():
    """Uma execução de cada variante e cenário do piloto, em N=50."""
    pilot = pd.read_csv(ROOT / "experiments" / "doe" / "doe_pilot.csv")
    pilot = pilot[(pilot["n_nodes"] == 50) & (pilot["seed"] == 100)]
    return pilot.reset_index(drop=True)


def test_row_config_maps_the_manifest_and_the_tuned_parameters():
    plan = small_plan()
    row = plan[
        (plan["scenario"] == "temporary_partition")
        & (plan["protocol_variant"] == "adaptive_ae_quiescent")
    ].iloc[0]
    config = helper.row_config(row, TUNED["adaptive_ae_quiescent"])
    assert config["network"]["partition"] == {"groups": 2, "start_ms": 0, "end_ms": 20_000}
    assert config["network"]["topology"] == "random_regular_connected"
    assert config["protocol"]["ae_interval_ms"] == 1000
    assert config["protocol"]["adaptive"]["quiescence_rounds"] == 3
    assert "ae_interval_ms" not in config["protocol"]["adaptive"]

    with pytest.raises(AssertionError):  # hiperparâmetros de outra variante
        helper.row_config(row, TUNED["push_tuned"])


def test_run_manifest_follows_the_contract_and_resumes(tmp_path):
    plan = small_plan()
    out = tmp_path / "pilot"
    first, _ = helper.run_manifest(plan.iloc[:12], TUNED, out, workers=2)
    summary, coverage = helper.run_manifest(plan, TUNED, out, workers=2)

    assert list(summary.columns) == SUMMARY_COLUMNS
    assert list(summary["run_id"]) == list(plan["run_id"])  # ordem do manifesto
    # wall_time_s idêntico: as 12 primeiras linhas não rodaram de novo
    again = summary.iloc[:12]["wall_time_s"].to_numpy()
    assert (again == first["wall_time_s"].to_numpy()).all()
    assert list(coverage.columns) == [
        "run_id", "scenario", "protocol_variant", "seed", "time_ms", "coverage",
    ]  # fmt: skip
    assert len(coverage) == len(plan) * 121  # 0 a 60.000 ms, a cada 500 ms
    assert coverage["coverage"].between(0, 1).all()

    table = helper.summarize_results(summary)
    assert len(table) == 30 and (table["runs"] == 1).all()


def test_factorial_rows_share_the_parameters_of_each_mechanism():
    plan = pd.read_csv(ROOT / "experiments" / "doe" / "doe_factorial.csv")
    rows = plan.groupby("protocol_variant").first()
    assert len(rows) == 12
    for variant, row in rows.iterrows():
        config = helper.row_config(row, helper.factorial_params(row, TUNED))
        protocol = config["protocol"]
        assert config["simulation"]["gossip_interval_ms"] == 500
        assert protocol["name"] == ("push_pull" if variant.startswith("push_pull") else "push")
        assert protocol["ae_interval_ms"] == (1000 if "_ae" in variant else None)
        adaptive = protocol["adaptive"]
        if "adaptive" in variant:
            assert adaptive["max_fanout"] == ADAPTIVE["max_fanout"]
            assert adaptive.get("quiescence_rounds") == (3 if variant.endswith("_q") else None)
        else:
            assert adaptive is None and protocol["fanout"] == 2


def test_guide_scores_conditions_and_recommends_per_priority():
    # duas condições; "slow" nunca é melhor, "broken" falha T95 em uma condição
    medians = {
        "fast": (1000, 900), "cheap": (3000, 100), "middle": (1500, 300),
        "slow": (4000, 950), "broken": (900, 50),
    }  # fmt: skip
    rows = [
        {"scenario": scenario, "n_nodes": 100, "protocol_variant": variant, "seed": seed,
         "t95_ms": None if variant == "broken" and scenario == "b" and seed == 0 else t95,
         "bytes_total": total_bytes}
        for scenario in ("a", "b") for variant, (t95, total_bytes) in medians.items() for seed in (0, 1)
    ]  # fmt: skip
    scored = helper.score_conditions(pd.DataFrame(rows))
    a = scored[scored["scenario"] == "a"].set_index("protocol_variant")
    assert a.loc["fast", "latency"] == pytest.approx(1000 / 900 - 1)  # "broken" é o mais rápido em a
    assert not a.loc["middle", "pareto"]  # "broken" domina em a
    b = scored[scored["scenario"] == "b"].set_index("protocol_variant")
    assert not b.loc["broken", "feasible"] and pd.isna(b.loc["broken", "pareto"])
    assert b.loc["middle", "pareto"] and not b.loc["slow", "pareto"]
    assert helper.recommend(scored) == {"latency": "fast", "traffic": "cheap", "balanced": "middle"}


def study_with(trials):
    """Estudo em memória com trials (t95_ms, bytes_total, simulações sem T95)."""
    study = optuna.create_study(directions=["minimize", "minimize"])
    for t95, total_bytes, without_t95 in trials:
        study.add_trial(
            optuna.trial.create_trial(
                values=[t95, total_bytes], user_attrs={"runs_without_t95": without_t95}
            )
        )
    return study


def test_select_trial_picks_the_pareto_point_closest_to_the_origin():
    table = tuning.select_trial(
        study_with(
            [
                (1000, 900, 0),  # fronteira: mais rápido, mais caro
                (2000, 400, 0),  # fronteira: normalizado (0,25; 0,29), o mais próximo
                (5000, 200, 0),  # fronteira: mais barato, mais lento
                (2500, 500, 0),  # dominado pelo segundo
                (500, 100, 3),  # melhor nos dois objetivos, mas inviável
            ]
        )
    )
    assert list(table["pareto"]) == [True, True, True, False, False]
    assert list(table["selected"]) == [False, True, False, False, False]


def test_select_trial_without_feasible_trial_takes_the_most_runs_with_t95():
    table = tuning.select_trial(study_with([(1000, 900, 5), (2000, 400, 2)]))
    assert list(table["selected"]) == [False, True]


def test_tuning_plan_uses_the_doe_scenarios_in_n_50():
    plan = tuning.tuning_plan("push_ae")
    assert len(plan) == 30 and plan["run_id"].is_unique
    assert set(plan["scenario"]) == {"stable", "loss_5pct", "churn_10pct"}
    assert set(plan["n_nodes"]) == {50} and set(plan["seed"]) == set(range(10))
