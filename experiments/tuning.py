"""Tuning dos hiperparâmetros com Optuna, em N=50. Regras no README, seção
"Regras do tuning".

Uso pela linha de comando, na raiz do projeto:
    python experiments/tuning.py

Os estudos ficam em results/tuning.db. Uma segunda chamada reaproveita os
trials já concluídos. O resultado é gravado em configs/tuned.yaml.
"""

from __future__ import annotations

import optuna
import pandas as pd
import yaml
from helper import BUDGET, RESULTS, ROOT, run_manifest

FAMILIES = ("push_tuned", "push_pull", "push_ae", "adaptive_ae")  # variantes do DOE
N_TRIALS = 30  # igual para as quatro famílias
TUNING_SEEDS = tuple(range(10))
TUNING_SCENARIOS = ("stable", "loss_5pct", "churn_10pct")
QUIESCENCE_GRID = tuple(range(1, 11))  # ablação: só quiescence_rounds varia


def suggest(trial, family):
    """Espaço de busca de cada família."""
    if family == "adaptive_ae_quiescent":
        return {"quiescence_rounds": trial.suggest_int("quiescence_rounds", 1, 10)}
    if family == "adaptive_ae":
        return {
            "min_fanout": trial.suggest_int("min_fanout", 1, 2),
            "max_fanout": trial.suggest_int("max_fanout", 3, 5),
            "duplicate_threshold": trial.suggest_float("duplicate_threshold", 0.1, 0.9),
            "timeout_threshold": trial.suggest_float("timeout_threshold", 0.1, 0.9),
            "ae_interval_ms": trial.suggest_categorical(
                "ae_interval_ms", [1000, 2000, 5000]
            ),
        }
    params = {
        "fanout": trial.suggest_int("fanout", 1, 5),
        "gossip_interval_ms": trial.suggest_categorical(
            "gossip_interval_ms", [250, 500, 1000]
        ),
    }
    if family == "push_ae":
        params["ae_interval_ms"] = trial.suggest_categorical(
            "ae_interval_ms", [1000, 2000, 5000]
        )
    return params


def tuning_plan(family, seeds=TUNING_SEEDS, scenarios=TUNING_SCENARIOS):
    """Linhas de manifesto do tuning: os cenários do DOE em N=50, com as seeds de treino."""
    design = pd.read_csv(ROOT / "experiments" / "doe" / "doe_design.csv")
    rows = design[
        (design["phase"] == "main")
        & (design["n_nodes"] == 50)
        & (design[BUDGET] == 4096)
        & (design["protocol_variant"] == family)
        & design["scenario"].isin(scenarios)
    ]
    plan = rows.drop(columns="seed").merge(pd.DataFrame({"seed": seeds}), how="cross")
    plan["run_id"] = plan["run_id"] + "-S" + plan["seed"].astype(str)
    return plan


def objective(trial, family, seeds=TUNING_SEEDS, frozen=None, workers=None):
    """Média de T95 e média de bytes nas simulações do trial.

    `frozen` são hiperparâmetros fixos, somados aos sugeridos pelo trial.
    """
    params = {**(frozen or {}), **suggest(trial, family)}
    plan = tuning_plan(family, seeds)
    summary, _ = run_manifest(plan, {family: params}, workers=workers)
    trial.set_user_attr("runs_without_t95", int(summary["t95_ms"].isna().sum()))
    # sem T95 conta como duration_ms: penaliza em vez de virar NaN na média
    t95 = summary["t95_ms"].fillna(plan["duration_ms"].iloc[0])
    return float(t95.mean()), float(summary["bytes_total"].mean())


def constraints(trial):
    """Optuna trata valor <= 0 como viável: todas as simulações atingiram T95."""
    return (trial.user_attrs["runs_without_t95"],)


def run_study(family, sampler, n_trials, seeds=TUNING_SEEDS, frozen=None, workers=None):
    """Reabre o estudo salvo em tuning.db e roda só os trials que faltam."""
    RESULTS.mkdir(exist_ok=True)
    study = optuna.create_study(
        study_name=family,
        directions=["minimize", "minimize"],  # T95 e bytes
        sampler=sampler,
        storage=f"sqlite:///{RESULTS / 'tuning.db'}",
        load_if_exists=True,
    )
    complete = optuna.trial.TrialState.COMPLETE
    remaining = n_trials - sum(trial.state == complete for trial in study.trials)
    if remaining > 0:
        study.optimize(
            lambda trial: objective(trial, family, seeds, frozen, workers),
            n_trials=remaining,
        )
    return study


def select_trial(study):
    """Tabela dos trials concluídos, com as colunas `pareto` e `selected`.

    Regra do README: entre os trials viáveis da fronteira de Pareto, normalizar
    os dois objetivos entre 0 e 1 e escolher o mais próximo de (0, 0); em
    empate, o de menor `bytes_total`. Sem trial viável, escolher o trial com
    menos simulações sem T95.
    """
    trials = pd.DataFrame(
        {
            "number": trial.number,
            **trial.params,
            "t95_ms": trial.values[0],
            "bytes_total": trial.values[1],
            "runs_without_t95": trial.user_attrs["runs_without_t95"],
        }
        for trial in study.trials
        if trial.state == optuna.trial.TrialState.COMPLETE
    )
    feasible = trials[trials["runs_without_t95"] == 0]
    values = feasible[["t95_ms", "bytes_total"]].to_numpy()
    # fronteira: nenhum outro trial é <= nos dois objetivos e < em um
    # O(n²), irrelevante com 30 trials
    on_front = [
        not any((other <= value).all() and (other < value).any() for other in values)
        for value in values
    ]
    front = feasible.loc[on_front]
    trials["pareto"] = trials["number"].isin(front["number"])
    if front.empty:
        best = trials.sort_values(["runs_without_t95", "bytes_total"]).iloc[0]
    else:
        objectives = front[["t95_ms", "bytes_total"]]
        span = (objectives.max() - objectives.min()).replace(0, 1)
        normalized = (objectives - objectives.min()) / span
        distance = (normalized**2).sum(axis=1) ** 0.5
        best = front.assign(distance=distance).sort_values(["distance", "bytes_total"]).iloc[0]
    trials["selected"] = trials["number"] == best["number"]
    return trials


def tune_all(n_trials=N_TRIALS, seeds=TUNING_SEEDS, workers=None):
    """Roda os quatro estudos e a grade de quiescência.

    Devolve (tuned, trials): os hiperparâmetros escolhidos por variante e a
    tabela de trials de cada estudo.
    """
    tuned, trials = {}, {}

    def choose(study):
        table = select_trial(study)
        trials[study.study_name] = table
        number = int(table.loc[table["selected"], "number"].iloc[0])
        return study.trials[number].params

    for family in FAMILIES:
        sampler = optuna.samplers.TPESampler(seed=0, constraints_func=constraints)
        tuned[family] = choose(run_study(family, sampler, n_trials, seeds, workers=workers))

    # ablação: adaptive_ae congelado, só quiescence_rounds varia, em grade
    grid = optuna.samplers.GridSampler({"quiescence_rounds": list(QUIESCENCE_GRID)})
    study = run_study(
        "adaptive_ae_quiescent",
        grid,
        len(QUIESCENCE_GRID),
        seeds,
        frozen=tuned["adaptive_ae"],
        workers=workers,
    )
    tuned["adaptive_ae_quiescent"] = {**tuned["adaptive_ae"], **choose(study)}
    return tuned, trials


if __name__ == "__main__":
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    tuned, trials = tune_all()
    path = ROOT / "configs" / "tuned.yaml"
    path.write_text(yaml.safe_dump(tuned, sort_keys=False), encoding="utf-8")
    for family, table in trials.items():
        print(f"\n{family}\n{table.sort_values('bytes_total').to_string(index=False)}")
    print(f"\n{path}:\n{path.read_text(encoding='utf-8')}")
