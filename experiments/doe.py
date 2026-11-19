"""Gera um plano experimental (DOE), sem executar o simulador.

Uso, na raiz do projeto:
    python experiments/doe.py

Arquivos produzidos:
    experiments/doe_pilot.csv    # 600 execuções de verificação piloto
    experiments/doe_design.csv   # 588 combinações de fatores (sem seed)
    experiments/doe_runs.csv     # 17.640 execuções planejadas (com seed)
    experiments/doe_scale.csv    # 540 execuções da varredura de escala
    experiments/doe_summary.txt  # contagem e definições

Valores de orçamento, tamanhos intermediários de rede, seeds e cronograma
são propostas de DOE, não especificações literais do PDF. A semântica de
churn, perda, partição, métricas e tuning está na seção "Especificação do
modelo" do README.
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

# Varredura de escala, separada do plano principal. Usa menos cenários e seeds
# porque o custo de uma execução cresce com N. Escolha experimental.
SCALE_NODES = (1_000, 10_000, 100_000)
SCALE_SEEDS = SEEDS[:10]

CHURN_PERIOD_MS = 5_000  # a cada período, o conjunto de nós offline é sorteado de novo
# A partição começa em t=0, junto com a injeção da atualização. Com início em
# 10 s, o Push já teria alcançado todos os nós (N=500: até 9 s em 20 seeds).
PARTITION_START_MS, PARTITION_END_MS = 0, 20_000

# (nome, protocolo, política de fanout, fanout, anti-entropy, quiescência).
# push_f1 é o baseline fixo, sem tuning. As outras variantes leem os
# hiperparâmetros de configs/tuned.yaml: as quatro famílias do PDF e a
# ablação com quiescência.
VARIANTS = (
    ("push_f1", "push", "fixed", 1, False, False),
    ("push_tuned", "push", "fixed", "tuned", False, False),
    ("push_pull", "push_pull", "fixed", "tuned", False, False),
    ("push_ae", "push", "fixed", "tuned", True, False),
    ("adaptive_ae", "push", "adaptive", "tuned", True, False),
    ("adaptive_ae_quiescent", "push", "adaptive", "tuned", True, True),
)

# Detalhes abaixo são escolhas propostas.
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
    "quiescence",
    "n_nodes",
    "packet_loss",
    "latency_model",
    "latency_min_ms",
    "latency_max_ms",
    "churn_fraction",
    "churn_period_ms",
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
    variant_name, protocol, policy, fanout, ae, quiescence = variant
    return {
        "phase": phase,
        "scenario": name,
        "protocol_variant": variant_name,
        "protocol": protocol,
        "fanout_policy": policy,
        "fanout_value": fanout,
        "anti_entropy": ae,
        "quiescence": quiescence,
        "n_nodes": n,
        "packet_loss": loss,
        "latency_model": latency_model,
        "latency_min_ms": lat_min,
        "latency_max_ms": lat_max,
        "churn_fraction": churn,
        "churn_period_ms": CHURN_PERIOD_MS if churn else "",
        "partition_groups": partition,
        "partition_start_ms": PARTITION_START_MS if partition else "",
        "partition_end_ms": PARTITION_END_MS if partition else "",
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

    # Piloto pequeno e prioritário: as cinco variantes com tuning, cinco
    # cenários centrais + interação loss 5% x churn 10%, duas escalas, 10 seeds.
    pilot_scenarios = (
        MAIN_SCENARIOS[0],  # estável
        MAIN_SCENARIOS[2],  # perda 5%
        MAIN_SCENARIOS[5],  # latência 10-200 ms
        MAIN_SCENARIOS[7],  # churn 10%
        MAIN_SCENARIOS[9],  # partição
        ("loss_5_churn_10", 0.05, "constant", 10, 10, 0.10, 0),
    )
    tuned_variants = tuple(v for v in VARIANTS if v[0] != "push_f1")
    pilot = []
    for scenario, variant, n, seed in product(
        pilot_scenarios, tuned_variants, (50, 500), range(100, 110)
    ):
        pilot.append(
            {
                "run_id": f"P{len(pilot) + 1:04d}",
                **record("pilot", scenario, variant, n, 4096),
                "seed": seed,
            }
        )
    write_csv(out / "doe_pilot.csv", COLS, pilot)

    # Varredura de escala: cenários estável, perda 5% e churn 10%; as seis
    # variantes; um orçamento. Os parâmetros são os mesmos congelados em N=50.
    scale_scenarios = (MAIN_SCENARIOS[0], MAIN_SCENARIOS[2], MAIN_SCENARIOS[7])
    scale = []
    for design_id, (scenario, variant, n) in enumerate(
        product(scale_scenarios, VARIANTS, SCALE_NODES), start=1
    ):
        row = record("scale", scenario, variant, n, 4096)
        scale.extend(
            {"run_id": f"E{design_id:03d}-S{seed}", **row, "seed": seed}
            for seed in SCALE_SEEDS
        )
    write_csv(out / "doe_scale.csv", COLS, scale)

    count_design = Counter(row["phase"] for row in design)
    count_runs = Counter(row["phase"] for row in runs)
    summary = (
        f"Piloto: {len(pilot)} runs (6 cenários x 5 variantes com tuning x 2 N "
        f"x 10 seeds)\n"
        f"Designs: {len(design)} (main={count_design['main']}, "
        f"interaction={count_design['interaction']})\n"
        f"Runs: {len(runs)} (main={count_runs['main']}, "
        f"interaction={count_runs['interaction']})\n"
        f"Seeds/teste: {SEEDS[0]}..{SEEDS[-1]} ({len(SEEDS)} por desenho)\n"
        f"Main: 10 cenários x {len(VARIANTS)} variantes x 4 tamanhos x 2 budgets "
        f"x 30 seeds = {count_runs['main']}\n"
        f"Interaction: 3 perdas x 3 churn x {len(VARIANTS)} variantes x 2 tamanhos "
        f"x 1 budget x 30 seeds = {count_runs['interaction']}\n"
        f"Escala (doe_scale.csv, fora do plano acima): 3 cenários "
        f"x {len(VARIANTS)} variantes x 3 tamanhos {SCALE_NODES} x 1 budget "
        f"x {len(SCALE_SEEDS)} seeds "
        f"({SCALE_SEEDS[0]}..{SCALE_SEEDS[-1]}) = {len(scale)}\n"
        f"Variantes: {', '.join(v[0] for v in VARIANTS)}. push_f1 é fixo; as "
        "demais usam configs/tuned.yaml.\n"
        "Tuning Optuna NÃO incluído: 30 trials por cada uma das 4 famílias do "
        "PDF em N=50, seeds de treino 0..9, e uma grade de quiescence_rounds.\n"
        f"Churn: churn_fraction é a fração de nós offline em todo instante; o "
        f"conjunto offline é sorteado de novo a cada {CHURN_PERIOD_MS} ms.\n"
        f"Partição: grupos por node_id % 2, de {PARTITION_START_MS} a "
        f"{PARTITION_END_MS} ms.\n"
        "A especificação completa está na seção 'Especificação do modelo' do README.\n"
        "Este script GERA o DOE; não implementa protocolos nem executa simulações.\n"
    )
    (out / "doe_summary.txt").write_text(summary, encoding="utf-8")
    print(summary, end="")
    print("\nArquivos gerados:")
    for name in (
        "doe_pilot.csv",
        "doe_design.csv",
        "doe_runs.csv",
        "doe_scale.csv",
        "doe_summary.txt",
    ):
        path = out / name
        print(f"  {path} ({path.stat().st_size:,} bytes)")
    assert len(scale) == 540
    assert len({r["run_id"] for r in scale}) == len(scale)
    assert len(pilot) == 600
    assert len(design) == 588
    assert len(runs) == 17_640
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
