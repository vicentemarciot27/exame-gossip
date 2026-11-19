"""Cola entre o simulador e o notebook. Não há lógica de Gossip aqui.

Uso pela linha de comando, na raiz do projeto:
    python experiments/helper.py experiments/doe/doe_pilot.csv

Os resultados vão para results/<nome do manifesto>_summary.csv e
results/<nome do manifesto>_coverage.csv.gz. Uma segunda chamada executa só as
linhas que faltam.
"""

from __future__ import annotations

import argparse
import multiprocessing
import time
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.simulation import Simulation

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
BASE_CONFIG = yaml.safe_load((ROOT / "configs" / "baseline.yaml").read_text("utf-8"))
BUDGET = "budget_bytes_per_node_per_1000ms"
PUSH_F1 = {"fanout": 1, "gossip_interval_ms": 500}  # baseline fixo, sem tuning
ID_COLUMNS = ["run_id", "scenario", "protocol_variant", "seed", "n_nodes"]


def run_trial(config, seed):
    """Devolve (resumo como dict, curva de cobertura com `time_ms` e `coverage`)."""
    start = time.perf_counter()
    simulation = Simulation(config, seed)
    summary = simulation.run()
    summary["wall_time_s"] = time.perf_counter() - start
    curve = pd.DataFrame(
        simulation.metrics.coverage_curve(), columns=["time_ms", "coverage"]
    )
    return summary, curve


def row_config(row, params):
    """Configuração de uma linha do manifesto, com os hiperparâmetros da variante.

    `params` usa os nomes do tuning: `fanout`, `gossip_interval_ms`,
    `ae_interval_ms` e os parâmetros do fanout adaptativo.
    """
    config = deepcopy(BASE_CONFIG)
    groups = int(row["partition_groups"])
    config["network"].update(
        nodes=int(row["n_nodes"]),
        topology=row["topology"],
        degree=int(row["degree"]),
        latency_ms=[int(row["latency_min_ms"]), int(row["latency_max_ms"])],
        packet_loss=float(row["packet_loss"]),
        churn_fraction=float(row["churn_fraction"]),
        partition={
            "groups": groups,
            "start_ms": int(row["partition_start_ms"]),
            "end_ms": int(row["partition_end_ms"]),
        }
        if groups
        else None,
    )
    if row["churn_fraction"]:
        config["network"]["churn_period_ms"] = int(row["churn_period_ms"])
    config["budget"]["bytes_per_node_per_interval"] = int(row[BUDGET])
    config["simulation"]["duration_ms"] = int(row["duration_ms"])

    params = dict(params)
    config["simulation"]["gossip_interval_ms"] = params.pop("gossip_interval_ms", 500)
    # o que sobra além de fanout e ae_interval_ms vai para o fanout adaptativo
    adaptive = {
        key: value
        for key, value in params.items()
        if key not in ("fanout", "ae_interval_ms")
    }
    config["protocol"] = {
        "name": row["protocol"],
        "fanout": params.get("fanout", 1),
        "ae_interval_ms": params.get("ae_interval_ms"),
        "adaptive": adaptive or None,
    }
    # falha se tuned.yaml não bate com o tratamento descrito no manifesto
    assert bool(params.get("ae_interval_ms")) == bool(row["anti_entropy"]), row
    assert bool(adaptive) == (row["fanout_policy"] == "adaptive"), row
    assert bool(adaptive.get("quiescence_rounds")) == bool(row["quiescence"]), row
    return config


def factorial_params(row, tuned):
    """Hiperparâmetros de uma linha do fatorial de mecanismos (`fanout_value` "common").

    Os mesmos valores em todas as combinações, para que a diferença venha do
    mecanismo e não do tuning: rodada de 500 ms, fanout fixo 2, anti-entropy a
    cada 1.000 ms e, no adaptativo, os limiares e a quiescência do tuning.
    """
    adaptive = tuned["adaptive_ae_quiescent"]
    params = {"gossip_interval_ms": 500}
    if row["fanout_policy"] == "fixed":
        params["fanout"] = 2
    else:
        for key in ("min_fanout", "max_fanout", "duplicate_threshold", "timeout_threshold"):
            params[key] = adaptive[key]
        if row["quiescence"]:
            params["quiescence_rounds"] = adaptive["quiescence_rounds"]
    if row["anti_entropy"]:
        params["ae_interval_ms"] = 1000
    return params


def _params(row, tuned):
    if row["fanout_value"] == "common":
        return factorial_params(row, tuned)
    return tuned[row["protocol_variant"]]


def _run_row(job):
    row, params = job
    summary, curve = run_trial(row_config(row, params), int(row["seed"]))
    ids = {column: row[column] for column in ID_COLUMNS}
    return {**ids, **summary}, curve.assign(run_id=row["run_id"])


def _load(out, plan):
    summary = pd.read_csv(f"{out}_summary.csv")
    coverage = pd.read_csv(f"{out}_coverage.csv.gz", dtype={"run_id": "category"})
    return summary[summary["run_id"].isin(plan["run_id"])], coverage


def run_manifest(plan, tuned, out=None, workers=None):
    """Executa cada linha de um manifesto do DOE. Retorna (summary_df, coverage_df).

    `tuned` associa cada variante aos seus hiperparâmetros (configs/tuned.yaml).
    Com `out` (prefixo de arquivo), os resultados são gravados à medida que
    terminam, e uma nova chamada só executa as linhas que faltam.
    """
    tuned = {"push_f1": PUSH_F1, **tuned}
    done = set()
    if out and Path(f"{out}_summary.csv").exists():
        done = set(pd.read_csv(f"{out}_summary.csv", usecols=["run_id"])["run_id"])
    # maiores primeiro: as curtas ficam para o fim e os workers terminam juntos
    todo = plan[~plan["run_id"].isin(done)].sort_values("n_nodes", ascending=False)
    jobs = [(row, _params(row, tuned)) for row in todo.to_dict("records")]

    summaries, curves = [], []

    def flush():
        if out and summaries:
            for frame, path in (
                (pd.concat(curves).round({"coverage": 4}), f"{out}_coverage.csv.gz"),
                (pd.DataFrame(summaries), f"{out}_summary.csv"),
            ):
                frame.to_csv(path, mode="a", header=not Path(path).exists(), index=False)
            summaries.clear()
            curves.clear()

    if jobs:
        if out:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
        last_flush = time.monotonic()
        with multiprocessing.Pool(workers) as pool:
            for summary, curve in pool.imap_unordered(_run_row, jobs):
                summaries.append(summary)
                curves.append(curve)
                if time.monotonic() - last_flush > 60:
                    flush()
                    last_flush = time.monotonic()
        flush()

    if out:
        summary_df, coverage_df = _load(out, plan)
    else:
        summary_df, coverage_df = pd.DataFrame(summaries), pd.concat(curves)
    # imap_unordered embaralha a ordem; volta à do manifesto
    summary_df = plan[["run_id"]].merge(summary_df, on="run_id")
    assert len(summary_df) == len(plan), "há execuções sem resultado"
    ids = summary_df[["run_id", "scenario", "protocol_variant", "seed"]]
    coverage_df = coverage_df.merge(ids, on="run_id")
    columns = ["run_id", "scenario", "protocol_variant", "seed", "time_ms", "coverage"]
    return summary_df, coverage_df[columns]


def summarize_results(summary_df, by=("scenario", "protocol_variant")):
    """Agrega por cenário e variante: medianas, quartis de T95 e fração de
    execuções que atingiram T95."""
    data = summary_df.assign(
        reached_t95=summary_df["t95_ms"].notna(),
        control_overhead=summary_df["bytes_control"] / summary_df["bytes_total"],
    )
    return (
        data.groupby(list(by), observed=True)
        .agg(
            runs=("run_id", "size"),
            fraction_reaching_t95=("reached_t95", "mean"),
            coverage_final_min=("coverage_final", "min"),
            t50_ms_median=("t50_ms", "median"),
            t95_ms_q1=("t95_ms", lambda s: s.quantile(0.25)),
            t95_ms_median=("t95_ms", "median"),
            t95_ms_q3=("t95_ms", lambda s: s.quantile(0.75)),
            bytes_until_t95_median=("bytes_until_t95", "median"),
            bytes_total_median=("bytes_total", "median"),
            control_overhead_median=("control_overhead", "median"),
            duplicates_median=("duplicates", "median"),
            timeouts_median=("timeouts", "median"),
            budget_drops_median=("budget_drops", "median"),
            recovery_ms_median=("recovery_ms", "median"),
        )
        .reset_index()
    )


def pareto_mask(values):
    """True nas linhas que nenhuma outra domina (todas as colunas a minimizar)."""
    values = np.asarray(values)
    # O(n²), irrelevante com dezenas de linhas
    return np.array(
        [not ((values <= value).all(axis=1) & (values < value).any(axis=1)).any() for value in values],
        dtype=bool,
    )


PRIORITIES = ("latency", "traffic", "balanced")


def score_conditions(summary_df, by=("scenario", "n_nodes")):
    """Medianas de T95 e bytes totais por condição e combinação, com a pontuação
    de cada prioridade (0 = melhor da condição).

    Viável: todas as execuções atingiram T95; só as viáveis são pontuadas.
    `latency` e `traffic`: excesso relativo ao melhor (0,1 = 10% pior).
    `balanced`: distância a (0, 0) com os dois objetivos normalizados entre 0 e 1,
    a regra do tuning.
    """
    by = list(by)
    table = (
        summary_df.groupby([*by, "protocol_variant"])
        .agg(
            t95_ms=("t95_ms", "median"),
            bytes_total=("bytes_total", "median"),
            feasible=("t95_ms", lambda s: s.notna().all()),
        )
        .reset_index()
    )
    scored = []
    for _, group in table[table["feasible"]].groupby(by):
        objectives = group[["t95_ms", "bytes_total"]]
        excess = objectives / objectives.min() - 1
        span = (objectives.max() - objectives.min()).replace(0, 1)
        normalized = (objectives - objectives.min()) / span
        scored.append(
            group.assign(
                latency=excess["t95_ms"],
                traffic=excess["bytes_total"],
                balanced=np.hypot(normalized["t95_ms"], normalized["bytes_total"]),
                pareto=pareto_mask(objectives),
            )
        )
    keys = [*by, "protocol_variant"]
    scores = pd.concat(scored)[[*keys, *PRIORITIES, "pareto"]]
    return table.merge(scores, on=keys, how="left")


def recommend(scored, by=("scenario", "n_nodes")):
    """Combinação recomendada em cada prioridade: a de menor pontuação média,
    entre as viáveis em todas as condições. Empate: menor pontuação de tráfego,
    ou de latência na prioridade de tráfego."""
    n_conditions = scored.groupby(list(by)).ngroups
    feasible = scored[scored["feasible"].astype(bool)]
    everywhere = feasible.groupby("protocol_variant").size() == n_conditions
    mean = (
        feasible[feasible["protocol_variant"].isin(everywhere[everywhere].index)]
        .groupby("protocol_variant")[list(PRIORITIES)]
        .mean()
    )
    return {
        priority: mean.sort_values([priority, "latency" if priority == "traffic" else "traffic"]).index[0]
        for priority in PRIORITIES
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Executa um manifesto do DOE")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()
    tuned = yaml.safe_load((ROOT / "configs" / "tuned.yaml").read_text("utf-8"))
    summary_df, _ = run_manifest(
        pd.read_csv(args.manifest), tuned, RESULTS / args.manifest.stem, args.workers
    )
    print(summarize_results(summary_df).to_string())
