# Gossip Simulator

Simulador de **eventos discretos** para comparar estratégias de disseminação Gossip em uma rede simulada: **Push**, **Push-Pull**, **Push + anti-entropy** e **Push com fanout adaptativo + anti-entropy**.

A pesquisa compara **cobertura**, **T50/T95**, **tráfego em bytes**, **duplicação**, **overhead de controle** e **recuperação após falhas**, sob latência heterogênea, perda de pacotes, churn e partições. O objetivo é testar *comportamento algorítmico*, não medir desempenho real de gRPC, containers ou sockets. Inicialmente, o foco é 50–500 nós simulados.

## Estrutura do projeto

```text
.
├── pyproject.toml
├── README.md
├── configs/
│   └── baseline.yaml
├── experiments/
│   ├── helper.py
│   └── notebook.ipynb
└── src/
    ├── __init__.py
    ├── simulation.py
    ├── network.py
    ├── protocols.py
    ├── metrics.py
    └── policies/
        ├── __init__.py
        ├── fanout.py
        ├── budget.py
        └── peer_selection.py
```

Os arquivos `__init__.py` podem estar vazios. Nesta estrutura mínima, **`src` é o nome do pacote Python** (`from src.simulation import Simulation`). Em um projeto maior, seria mais convencional ter `src/gossip_sim/`, mas não é necessário agora.

### Responsabilidade de cada arquivo

| Arquivo | Responsabilidade |
|---|---|
| `src/simulation.py` | Cria o `simpy.Environment`, configura nós, inicia processos periódicos, injeta atualizações, agenda eventos de falha e encerra a simulação. Pode conter `Node` inicialmente. |
| `src/network.py` | Guarda a topologia (peers), transporta mensagens **somente pelo relógio simulado**, aplica latência, perda, churn e partições. Único lugar autorizado a entregar mensagens. |
| `src/protocols.py` | Implementa Push, Push-Pull e anti-entropy: decide quais mensagens enviar e quando reconciliar versões. Não manipula a fila de eventos diretamente. |
| `src/metrics.py` | Registra eventos e calcula curvas de cobertura, T50, T95, bytes, controle, duplicatas e tempo de recuperação. Não interfere nas decisões dos nós. |
| `src/policies/fanout.py` | Fanout fixo e adaptativo. A política adaptativa usa apenas estatísticas **locais** observáveis pelo nó. |
| `src/policies/budget.py` | Aplica orçamento de comunicação por nó e janela de tempo. Inclui mensagens de dados, controle e reparos. |
| `src/policies/peer_selection.py` | Escolha de destinatários (ex.: uniforme sem reposição); opera sobre a visão local de peers. |
| `configs/*.yaml` | Cenários declarativos: duração, nós, topologia, latência, perda, churn, orçamento e parâmetros do protocolo. |
| `experiments/helper.py` | Cola entre simulador e notebook: lê configurações, executa o grid de cenários/protocolos/seeds e devolve `pandas.DataFrame`s. **Sem lógica de Gossip aqui**. |
| `experiments/notebook.ipynb` | Define hipóteses, seleciona cenários, executa repetições, constrói gráficos/tabelas, interpreta resultados e registra limitações. |
| `pyproject.toml` | Define o pacote, as dependências e os extras para notebooks e testes. |

## Bibliotecas e por que usar cada uma

O projeto separa bibliotecas necessárias **para simular** das bibliotecas usadas **para experimentar e analisar**.

### Dependências principais

| Biblioteca | Uso |
|---|---|
| [SimPy](https://simpy.readthedocs.io/) | **Motor de eventos discretos**. Oferece relógio virtual (`env.now`), processos (`env.process`) e agendamento (`yield env.timeout`). Nada precisa esperar em tempo real. |
| [NumPy](https://numpy.org/doc/) | Geradores pseudoaleatórios e seeds para peer selection, perdas e latências; permite separar fluxos de aleatoriedade por componente. |
| [NetworkX](https://networkx.org/documentation/stable/) | Gera e guarda grafos/topologias e consultas de vizinhança; não simula a transmissão. |
| [PyYAML](https://pyyaml.org/wiki/PyYAMLDocumentation) | Lê os arquivos `configs/*.yaml` usando `yaml.safe_load`. |

### Extra `experiments`

| Biblioteca | Uso |
|---|---|
| [JupyterLab](https://jupyterlab.readthedocs.io/) | Ambiente para editar e executar `experiments/notebook.ipynb`. |
| [ipykernel](https://ipykernel.readthedocs.io/) | Executa o código Python nas células do notebook, usando o ambiente do projeto. |
| [pandas](https://pandas.pydata.org/docs/) | Tabelas de repetições e séries temporais, agregação por protocolo e exportação CSV. |
| [Matplotlib](https://matplotlib.org/stable/) | Controle fino de figuras de cobertura ao longo do tempo, tráfego e T95. |
| [Seaborn](https://seaborn.pydata.org/) | Gráficos estatísticos sobre os DataFrames, incluindo distribuições e intervalos. |
| [SciPy](https://docs.scipy.org/doc/scipy/) | Estatísticas e estimativas de incerteza, quando adequadas à métrica. |
| [Optuna](https://optuna.readthedocs.io/) | **Opcional no fluxo científico**: ajuste controlado de parâmetros em conjunto de treino, antes da avaliação final. Não deve otimizar com as próprias seeds de teste. |

### Desenvolvimento e empacotamento

| Ferramenta | Uso |
|---|---|
| [pytest](https://docs.pytest.org/) (`dev`) | Testes determinísticos dos protocolos, do transporte, do orçamento e da reprodutibilidade. |
| [Hatchling](https://hatch.pypa.io/) (`build-system`) | Permite instalar o código local em modo editável para importar `src` do notebook, sem hacks no `sys.path`. |
| [uv](https://docs.astral.sh/uv/) | Gerencia Python, ambiente virtual, dependências e lockfile; é uma ferramenta externa, não uma dependência Python do projeto. |

**Não são necessários** Docker, gRPC, Prometheus, OpenTelemetry ou `netem` para esta versão: falhas e atrasos são modelados por eventos simulados.

## Instalação e execução

Na raiz do repositório, com `uv` instalado:

```bash
uv sync --extra experiments --extra dev
uv run --extra experiments jupyter lab experiments/notebook.ipynb
```

Como alternativa com `pip` (Python 3.11+):

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e '.[experiments,dev]'
python -m jupyter lab experiments/notebook.ipynb
```

`uv sync` cria um ambiente e instala o pacote em modo editável. Durante o desenvolvimento, modifique `src/*.py` e reinicie/recarregue o kernel do notebook se necessário. `uv.lock` deve ser versionado para congelar as versões resolvidas.

**Observação:** os arquivos de Python desta estrutura precisam ser implementados; o notebook entregue é um **roteiro de experimento**, não uma simulação pronta para executar. O arquivo `configs/baseline.yaml` incluído é uma proposta inicial de configuração.

## Contrato simples entre notebook e simulador

Sugestão de interface pública em `experiments/helper.py`:

```python
def run_many(config: dict, variants: dict, seeds: list[int], scenario: str):
    """Executa todas as combinações variante x seed do cenário.

    Retorna (summary_df, coverage_df), ambos pandas.DataFrame.
    """
    # TODO: instanciar Simulation e obter as métricas de cada rodada.
    ...
```

Cada variante muda **somente** a escolha de protocolo/políticas; a infraestrutura simulada deve ser a mesma. O helper pode começar sequencial e ser paralelizado depois.

**`summary_df`: uma linha por execução**, colunas sugeridas:

```text
scenario, protocol, seed, n_nodes, coverage_final,
t50_ms, t95_ms, bytes_total, bytes_control, duplicates
```

**`coverage_df`: múltiplas linhas por execução**, colunas:

```text
scenario, protocol, seed, time_ms, coverage
```

Defina `coverage` como fração entre 0 e 1. `t95_ms` deve ser `NaN`/não atingido se uma rodada nunca alcançar 95% até o horizonte da simulação; não exclua silenciosamente esses resultados. Se houver churn, **documente o denominador** da cobertura (por exemplo, coorte elegível em cada instante).

## Organização do `experiments/notebook.ipynb`

O notebook acompanha o fluxo de uma pesquisa, de cima para baixo:

1. **Objetivo e hipóteses (Markdown):** comparar cobertura, T95 e tráfego dos baselines contra o adaptativo + anti-entropy sob o mesmo orçamento.
2. **Imports, configuração e seeds (código):** `yaml.safe_load`, tabelas de variantes, lista fixa de sementes e horizonte simulado.
3. **Sanity check / baseline (código + Markdown):** executar uma rede estável sem perdas e comparar a curva Push com a tendência do modelo teórico em rede completa.
4. **Definição dos cenários (código):** estável, perda, atraso heterogêneo, churn e partição; variar um fator de cada vez inicialmente.
5. **Execução do grid (código):** chamar **uma função do `helper.py`** para cada cenário e obter `summary_df` e `coverage_df`.
6. **Qualidade dos dados (código):** conferir formato, total de runs, valores ausentes, eventos de T95 não atingido, orçamento e seeds.
7. **Gráficos (código):** cobertura × tempo; distribuição T95; bytes × T95; cobertura final × tráfego.
8. **Análise estatística (código + Markdown):** medianas/intervalos, variabilidade entre seeds, trade-offs e casos em que o adaptativo perde.
9. **Conclusões e limitações (Markdown):** hipóteses confirmadas ou refutadas, limites do modelo e ameaças à validade.

### Exemplos de células (API a implementar)

```python
from pathlib import Path
import yaml
from helper import run_many

ROOT = Path.cwd().resolve()
if ROOT.name == "experiments":
    ROOT = ROOT.parent

with (ROOT / "configs" / "baseline.yaml").open() as f:
    config = yaml.safe_load(f)

variants = {
    "push_f1": {"protocol": "push", "fanout": 1, "anti_entropy": False},
    "push_f3": {"protocol": "push", "fanout": 3, "anti_entropy": False},
    "push_ae": {"protocol": "push", "fanout": 1, "anti_entropy": True},
    "adaptive_ae": {"protocol": "push", "fanout": "adaptive", "anti_entropy": True},
}

summary_df, coverage_df = run_many(
    config=config,
    variants=variants,
    seeds=list(range(30)),
    scenario="baseline",
)
```

```python
import seaborn as sns
import matplotlib.pyplot as plt

sns.lineplot(
    data=coverage_df,
    x="time_ms",
    y="coverage",
    hue="protocol",
    estimator="mean",
    errorbar=("ci", 95),
)
plt.ylabel("Cobertura (fração)")
plt.show()
```

**Importante:** as funções/colunas acima estabelecem um contrato **proposto**, que deve ser implementado em `helper.py` e `src/`. Até isso acontecer, as células de execução são exemplos.

## Reprodutibilidade e comparações justas

- **Mesmo cenário e orçamento de bytes** por nó/intervalo para todos os protocolos (incluindo anti-entropy e controle).
- **Seeds registradas e separadas por componente:** topologia, falhas e latência não devem mudar indevidamente entre tratamentos; o RNG de um protocolo não deve consumir o RNG de outro.
- **Mesmo horizonte** e mesma definição de coorte/cobertura; reportar não convergência e execuções sem T95.
- **Controle de erros:** primeiro validar comportamento em rede completa sem falhas; depois adicionar atraso, perdas e churn isoladamente.
- **Experimentos repetidos:** rodar múltiplas seeds, apresentar dispersão e não apenas médias.
- **Optuna (se usado):** ajustar em conjunto de cenários/seeds separado dos experimentos finais.
- **Logs/CSV:** salvar resultados brutos, configuração, seed e versão do código. Evitar commit de arquivos de saída grandes.

## Implementação (timeline)

1. `simulation.py` + `network.py` + `protocols.py`: Push simples, sem falhas, um evento versionado.
2. `metrics.py`: curva de cobertura, T50/T95 e bytes.
3. `policies/fanout.py` e `peer_selection.py`: baselines fixos e comparação inicial.
4. `network.py`: perda, latência heterogênea, churn e partição.
5. `protocols.py`: Push-Pull e anti-entropy; `budget.py`: teto de bytes.
6. `fanout.py`: heurística adaptativa baseada em estatísticas locais; benchmark repetido no notebook.

## Rastreabilidade com a apresentação (8 slides) e DOE completo

**Status:** este repositório continua sendo um *esqueleto de projeto*, não uma implementação do simulador. O notebook original contém exemplos comentados; `experiments/doe.py` **gera somente planos de execução**, não resultados científicos.

### Experimentos exigidos pela proposta original

| Parte do PDF | O que deve ser avaliado | Como atender na DES |
|---|---|---|
| Pág. 3 | Push em rede completa sem falhas, `n=100`, fanout 1 e 3; comparar com curva analítica | Validação antes do benchmark, usando rodadas síncronas e seeds |
| Págs. 4–5 | Push; Push-Pull; Push+AE; Adaptativo+AE | Quatro famílias de protocolos sobre o mesmo motor |
| Pág. 5 | `50–500` nós; fanout fixo/adaptativo; perdas; churn; latência; orçamento bytes/nó/intervalo | Variar os fatores, usando as mesmas condições exógenas para todos os protocolos |
| Pág. 5 | Cobertura, T50, T95, tráfego por atualização, duplicação, recuperação e overhead | Emitir métricas por evento e agregar com definições explícitas |
| Pág. 5 | Ajustar parâmetros com Optuna em `N=50`, mesmo número de tentativas por protocolo | Estudo de tuning **separado** do benchmark final; seeds de treino/teste distintas |
| Pág. 6 | Estável (0%, 10 ms, 0% churn); perda 1–10%; atraso 10–200 ms; churn 5–20%; partição de dois grupos | Cinco famílias de cenário, com níveis explícitos |
| Págs. 3, 6 | Efeito conjunto de fanout adaptativo e AE sob *churn e perdas*; relatar casos sem ganho | DOE fatorial extra `packet_loss × churn`, comparação pareada com baselines |
| Págs. 6–7 | Escalabilidade, tráfego/nó × N, recuperação após reconexão, seeds e dispersão | Varredura de N; tabela e gráficos por N; teste de falhas com reconexão |
| Págs. 7–8 | Nó por processo, Docker/Go/gRPC/netem/OTel (arquitetura antiga) | **Mudança de escopo:** nó como entidade virtual, transporte de eventos, métricas em CSV. Esta equivalência precisa ser aceita pelo professor; não mede rede real. |

Os trabalhos relacionados da **página 2** (SWIM, HyParView, Plumtree e GossipSub) contextualizam a pesquisa; o PDF **não exige implementar** cada um deles.

### Plano DOE

Execute na raiz:

```bash
python experiments/doe.py
```

Saídas:

- `experiments/doe_pilot.csv`: **480 execuções** (quatro famílias, dois N, 6 cenários incluindo perda+churn, dez seeds).
- `experiments/doe_design.csv`: **490 combinações** de fatores do plano completo, ainda sem seeds.
- `experiments/doe_runs.csv`: **14.700 execuções planejadas**, cada uma com seed.
- `experiments/doe_summary.txt`: relatório com contagens.

**Fase principal:** 10 configurações de cenário × 5 variantes × 4 tamanhos de rede × 2 orçamentos × 30 seeds = **12.000** execuções.

- Dez cenários = estável (1), perda de pacotes 1/5/10% (3), latência heterogênea 10–100 e 10–200 ms (2), churn 5/10/20% (3), partição temporária (1).
- Cinco variantes = `push_f1`, `push_f3`, `push_pull`, `push_ae`, `adaptive_ae`. O Push com fanout=3 é uma **variante adicional** de baseline: o PDF cita fanout fixo/adaptativo e usa f=1/f=3 no gráfico analítico, mas lista quatro famílias de protocolos.
- N = 50, 100, 250, 500; orçamento = 2.048 ou 4.096 bytes/nó a cada 1.000 ms; 30 seeds reservadas ao teste (1000..1029).

**Interação crítica:** perda 1/5/10% × churn 5/10/20% × 5 variantes × N=100/500 × orçamento 4.096 × 30 seeds = **2.700** execuções adicionais. Assim, a hipótese da página 3 é testada diretamente.

**Optuna é uma etapa separada, não incluída nesses 14.700 casos**: em N=50, reservar o mesmo número de tentativas (por exemplo, 30) para as quatro famílias de protocolos, usando seeds de treinamento distintas das de avaliação. Fixar antecipadamente a função objetivo e as restrições (cobertura, T95, orçamento) para evitar otimização orientada pelos resultados finais.

**Importante: os níveis 2.048/4.096 bytes, tamanhos 100/250, 30 seeds, duração de 60 s, distribuição uniforme das latências, cronograma de partição 10–30 s e grau 8 são decisões propostas para o DOE**, não valores determinados pelo PDF. Os valores de perda, churn e as cinco famílias de cenário são extraídos da apresentação. Os detalhes temporais do churn não são definidos pelo PDF e **precisam ser especificados antes de rodar**.

### Checklist de implementação antes de qualquer resultado válido

1. **Modelo de eventos:** implementar `Simulation` com SimPy; relógio e ordem determinística de eventos simultâneos.
2. **Estado local:** `Node` com ID, peers, versões, IDs vistos, contadores de duplicatas/timeouts e bytes; impedir vazamento de estado global para políticas.
3. **Mensagens versionadas:** criação de atualização por ID e versão, entrega/deduplicação e atualização da versão local.
4. **Membership / peers:** política de visão local e transições join/leave; estabelecer o que acontece com a memória do nó na reconexão.
5. **Transporte:** latência, perdas e partições com regras explícitas para mensagens em trânsito e endpoints que mudam de estado.
6. **Protocolos:** Push, Push-Pull, anti-entropy periódica e combinação Push adaptativo+AE; configurar frequência e tamanhos reais das mensagens.
7. **Políticas:** seleção de peers, fanout fixo/adaptativo apenas por estatísticas locais; limites de fanout; orçamento de dados, controle e reparo, cobrado no envio.
8. **Métricas por evento:** cobertura sobre coorte elegível, T50/T95 (inclusive quando não atingidos), bytes de dados/controle/reparos, duplicações, overhead, tráfego/nó e tempo de recuperação após retorno da conectividade.
9. **Validação analítica:** reproduzir o modelo Push sem falhas da pág. 3 com N=100 e fanout 1/3; testes para perda=100%, partição, deduplicação, orçamento e reprodutibilidade.
10. **Helper do notebook:** implementar `run_one` e `run_manifest` (ou adaptar `run_many`) para consumir as linhas `doe_*.csv`, registrar status e salvar dados brutos sem depender da ordem das execuções.
11. **Tuning:** Optuna em N=50 com igual orçamento de tentativa por família e seeds de validação separadas do teste final.
12. **Análise:** piloto → estudo principal → interação; comparação pareada por cenário/seed, dispersão, cobertura×T95×tráfego, recuperação e casos em que o adaptativo perde.
13. **Relatório:** registrar versões, seeds, configurações, hipóteses, casos não convergentes e a limitação fundamental de que uma DES **não** valida custos de rede/sockets/containers reais.

### Como usar o DOE no notebook

O notebook deve **carregar o manifesto pronto**, em vez de manter uma lista de cenários duplicada em células:

```python
from pathlib import Path
import pandas as pd

ROOT = Path.cwd().resolve()
if ROOT.name == "experiments":
    ROOT = ROOT.parent

plan = pd.read_csv(ROOT / "experiments" / "doe_pilot.csv")
print(plan.groupby(["phase", "scenario"]).size())

# A implementar em experiments/helper.py:
# from helper import run_manifest
# summary_df, coverage_df = run_manifest(plan)
```

**Não executar a matriz completa antes da validação.** Primeiro rodar o caso analítico sem falhas e um piloto pequeno, inspecionar os logs e as métricas, e só depois avançar às 14.700 execuções. O volume total é uma proposta de cobertura experimental, não uma obrigação do PDF nem uma garantia de runtime aceitável.
