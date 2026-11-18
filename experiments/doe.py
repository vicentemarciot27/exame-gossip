"""Gera um plano experimental (DOE), sem executar o simulador.

Uso, na raiz do projeto:
    python experiments/doe.py

Arquivos produzidos:
    experiments/doe_pilot.csv    # 480 execuções de verificação piloto
    experiments/doe_design.csv   # 490 combinações de fatores (sem seed)
    experiments/doe_runs.csv     # 14.700 execuções planejadas (com seed)
    experiments/doe_summary.txt  # contagem e definições

Valores de orçamento, tamanhos intermediários de rede, seeds e cronograma
são propostas de DOE, não especificações literais do PDF.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from itertools import product
from pathlib import Path

OUT = Path(__file__).resolve().parent
NODES = (50, 100, 250, 500)
BUDGETS = (2048, 4096)  # bytes/nó por janela de 1000 ms; escolha experimental
SEEDS = tuple(range(1000, 1030))  # seeds de teste, distintas das de tuning
DURATION_MS = 60_000  # escolha experimental
TOPOLOGY = "random_regular_connected"  # escolha experimental; grau=8
DEGREE = 8

# Quatro famílias previstas no PDF; push_f3 é baseline fixo extra.
VARIANTS = (
    ("push_f1", "push", "fixed", 1, False),
    ("push_f3", "push", "fixed", 3, False),
    ("push_pull", "push_pull", "fixed", 1, False),
    ("push_ae", "push", "fixed", 1, True),
    ("adaptive_ae", "push", "adaptive", "1..5", True),
)

# Grupos são isolados entre 10 e 30 s. Detalhes abaixo são escolhas propostas.
# Fatores não ativos no cenário são zerados e o intervalo de latência é 10 ms.
MAIN_SCENARIOS = (
    ("stable", 0.00, "constant", 10, 10, 0.00, 0),
    ("loss_1pct", 0.01, "constant", 10, 10, 0.00, 0),
    ("loss_5pct", 0.05, "constant", 10, 10, 0.00, 0),
    ("loss_10pct", 0.10, "constant", 10, 10, 0.00, 0),
    ("latency_10_100ms", 0.00, "uniform", 10, 100, 0.00, 0),
    ("latency_10_200ms", 0.00, "uniform", 10, 200, 0.00, 0),
    ("churn_5pct", 0.00, "constant", 10, 10, 0.05, 0),
    ("churn_10pct", 0.00, "constant", 10, 10, 0.10, 0),
    ("churn_20pct", 0.00, "constant", 10, 10, 0.20, 0),
    ("temporary_partition", 0.00, "constant", 10, 10, 0.00, 2),
)

COLS = (
    "run_id",
    "phase",
    "scenario",
    "protocol_variant",
    "protocol",
    "fanout_policy",
    "fanout_value",
    "anti_entropy",
    "n_nodes",
    "packet_loss",
    "latency_model",
    "latency_min_ms",
    "latency_max_ms",
    "churn_fraction",
    "partition_groups",
    "partition_start_ms",
    "partition_end_ms",
    "budget_bytes_per_node_per_1000ms",
    "seed",
    "duration_ms",
    "topology",
    "degree",
)


def record(phase, scenario, variant, n, budget):
    name, loss, latency_model, lat_min, lat_max, churn, partition = scenario
    variant_name, protocol, policy, fanout, ae = variant
    return {
        "phase": phase,
        "scenario": name,
        "protocol_variant": variant_name,
        "protocol": protocol,
        "fanout_policy": policy,
        "fanout_value": fanout,
        "anti_entropy": ae,
        "n_nodes": n,
        "packet_loss": loss,
        "latency_model": latency_model,
        "latency_min_ms": lat_min,
        "latency_max_ms": lat_max,
        "churn_fraction": churn,
        "partition_groups": partition,
        "partition_start_ms": 10_000 if partition else "",
        "partition_end_ms": 30_000 if partition else "",
        "budget_bytes_per_node_per_1000ms": budget,
        "duration_ms": DURATION_MS,
        "topology": TOPOLOGY,
        "degree": DEGREE,
    }


def design_rows():
    # Cinco famílias de cenários do PDF, desdobradas em dez configurações.
    for scenario, variant, n, budget in product(
        MAIN_SCENARIOS, VARIANTS, NODES, BUDGETS
    ):
        yield record("main", scenario, variant, n, budget)

    # Experimento fatorial de interação, necessário para a hipótese da pág. 3.
    # Mantemos 100/500 nós e um orçamento para controlar o tamanho do estudo.
    for loss, churn, variant, n in product(
        (0.01, 0.05, 0.10), (0.05, 0.10, 0.20), VARIANTS, (100, 500)
    ):
        scenario = (
            f"loss_{round(loss * 100)}_churn_{round(churn * 100)}",
            loss,
            "constant",
            10,
            10,
            churn,
            0,
        )
        yield record("interaction", scenario, variant, n, 4096)


def write_csv(path, headers, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def main(output_dir: Path | None = None):
    out = (output_dir or OUT).resolve()
    out.mkdir(parents=True, exist_ok=True)
    design = list(design_rows())
    runs = []
    for design_id, row in enumerate(design, start=1):
        for seed in SEEDS:
            runs.append({"run_id": f"D{design_id:04d}-S{seed}", **row, "seed": seed})

    write_csv(
        out / "doe_design.csv",
        COLS,
        (
            {"run_id": f"D{i:04d}", **r, "seed": ""}
            for i, r in enumerate(design, start=1)
        ),
    )
    write_csv(out / "doe_runs.csv", COLS, runs)

    # Piloto pequeno e prioritário: quatro famílias prometidas, cinco
    # cenários centrais + interação loss 5% x churn 10%, duas escalas, 10 seeds.
    pilot_scenarios = (
        MAIN_SCENARIOS[0],  # estável
        MAIN_SCENARIOS[2],  # perda 5%
        MAIN_SCENARIOS[5],  # latência 10-200 ms
        MAIN_SCENARIOS[7],  # churn 10%
        MAIN_SCENARIOS[9],  # partição
        ("loss_5_churn_10", 0.05, "constant", 10, 10, 0.10, 0),
    )
    promised_variants = tuple(v for v in VARIANTS if v[0] != "push_f3")
    pilot = []
    for scenario, variant, n, seed in product(
        pilot_scenarios, promised_variants, (50, 500), range(100, 110)
    ):
        pilot.append(
            {
                "run_id": f"P{len(pilot) + 1:04d}",
                **record("pilot", scenario, variant, n, 4096),
                "seed": seed,
            }
        )
    write_csv(out / "doe_pilot.csv", COLS, pilot)

    count_design = Counter(row["phase"] for row in design)
    count_runs = Counter(row["phase"] for row in runs)
    summary = (
        f"Piloto: {len(pilot)} runs (6 cenários x 4 famílias x 2 N x 10 seeds)\n"
        f"Designs: {len(design)} (main={count_design['main']}, "
        f"interaction={count_design['interaction']})\n"
        f"Runs: {len(runs)} (main={count_runs['main']}, "
        f"interaction={count_runs['interaction']})\n"
        f"Seeds/teste: {SEEDS[0]}..{SEEDS[-1]} ({len(SEEDS)} por desenho)\n"
        f"Main: 10 cenários x 5 variantes x 4 tamanhos x 2 budgets "
        f"x 30 seeds = {count_runs['main']}\n"
        f"Interaction: 3 perdas x 3 churn x 5 variantes x 2 tamanhos "
        f"x 1 budget x 30 seeds = {count_runs['interaction']}\n"
        "Tuning Optuna NÃO incluído: planejar separadamente 30 trials "
        "por cada uma das 4 famílias do PDF em N=50, com seeds de treino "
        "diferentes das de teste.\n"
        "Atenção: churn_fraction é magnitude, não o processo temporal de join/leave. "
        "Antes de rodar, definir taxa/duração/reentrada, coorte elegível, "
        "distribuição das latências, política de partição e orçamento de AE.\n"
        "Este script GERA o DOE; não implementa protocolos nem executa simulações.\n"
    )
    (out / "doe_summary.txt").write_text(summary, encoding="utf-8")
    print(summary, end="")
    print("\nArquivos gerados:")
    for name in ("doe_pilot.csv", "doe_design.csv", "doe_runs.csv", "doe_summary.txt"):
        path = out / name
        print(f"  {path} ({path.stat().st_size:,} bytes)")
    assert len(pilot) == 480
    assert len(design) == 490
    assert len(runs) == 14_700
    assert len({r["run_id"] for r in runs}) == len(runs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gerar matriz DOE de Gossip")
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT,
        help="Pasta de saída (padrão: pasta do doe.py)",
    )
    args = parser.parse_args()
    main(args.out)
