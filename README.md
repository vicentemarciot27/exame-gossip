# Gossip Simulator

Simulador de eventos discretos que compara quatro estratégias de disseminação Gossip: Push, Push-Pull, Push + anti-entropy e Push com fanout adaptativo + anti-entropy.

As métricas são cobertura, T50/T95, tráfego em bytes, duplicação, overhead de controle e recuperação após falhas, sob latência heterogênea, perda de pacotes, churn e partições. O simulador mede o comportamento dos algoritmos, não o desempenho real de gRPC, containers ou sockets. O DOE principal usa 50–500 nós simulados. Uma varredura de escala separada usa 1.000, 10.000 e 100.000 nós.

O projeto também propõe um passo a passo para escolher os mecanismos de Gossip por condição de rede e prioridade (latência, tráfego ou equilíbrio): importância dos hiperparâmetros, fatorial dos mecanismos com parâmetros comuns, fronteira de Pareto por condição, recomendação e validação em condições novas. A seção "Guia de escolha de mecanismos" resume o método e os resultados.

## Instalação e execução

Na raiz do repositório, com `uv` instalado:

```bash
uv sync --extra experiments --extra dev
uv run --extra experiments jupyter lab experiments/notebook.ipynb
```

Com `pip` (Python 3.11+):

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -e '.[experiments,dev]'
python -m jupyter lab experiments/notebook.ipynb
```

`uv sync` cria o ambiente e instala o pacote em modo editável. Depois de alterar `src/*.py`, reinicie o kernel do notebook. Versione o `uv.lock`: ele fixa as versões resolvidas.

Testes: `uv run pytest -q`.

Testes e experimentos usam os extras: `uv run --extra experiments --extra dev pytest -q`.

Reprodução dos experimentos, na raiz do repositório. Cada comando reaproveita o que já estiver em `results/`:

```bash
uv run --extra experiments python experiments/doe.py --out experiments/doe       # manifestos
uv run --extra experiments python experiments/tuning.py                          # Optuna, grava configs/tuned.yaml
uv run --extra experiments python experiments/helper.py experiments/doe/doe_pilot.csv
uv run --extra experiments python experiments/helper.py experiments/doe/doe_runs.csv
uv run --extra experiments python experiments/helper.py experiments/doe/doe_scale.csv --workers 14
uv run --extra experiments python experiments/helper.py experiments/doe/doe_factorial.csv
uv run --extra experiments python experiments/helper.py experiments/doe/doe_validation.csv --workers 22
uv run --extra experiments jupyter nbconvert --to notebook --execute --inplace \
    --ExecutePreprocessor.timeout=-1 experiments/notebook.ipynb
```

O notebook executa as mesmas etapas pelas mesmas funções. Rodar os comandos antes evita uma execução de horas dentro do kernel. `results/` não precisa ser versionado: `tuning.db`, `*_summary.csv` e `*_coverage.csv.gz` são gerados de novo pelos comandos acima.

## Estrutura do projeto

```text
.
├── pyproject.toml
├── README.md
├── configs/
│   ├── baseline.yaml
│   └── tuned.yaml          # exportado pelo tuning
├── experiments/
│   ├── helper.py
│   ├── tuning.py
│   ├── doe.py
│   ├── doe/                # manifestos CSV gerados por doe.py
│   └── notebook.ipynb
├── results/                # gerado pelos experimentos
├── tests/
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

Os arquivos `__init__.py` podem estar vazios. `src` é o nome do pacote Python (`from src.simulation import Simulation`). Um projeto maior usaria `src/gossip_sim/`.

### Responsabilidade de cada arquivo

| Arquivo | Responsabilidade |
|---|---|
| `src/simulation.py` | Cria o `simpy.Environment`, configura nós, inicia processos periódicos, injeta atualizações, agenda eventos de falha e encerra a simulação. Pode conter `Node` inicialmente. |
| `src/network.py` | Guarda a topologia, sorteia peers (`sample_peers`) sem montar a lista de vizinhos, transporta mensagens só pelo relógio simulado, aplica latência, perda, churn e partições. Único módulo que entrega mensagens. |
| `src/protocols.py` | Implementa Push, Push-Pull e anti-entropy: decide quais mensagens enviar e quando reconciliar versões. Não manipula a fila de eventos diretamente. |
| `src/metrics.py` | Registra eventos e calcula curvas de cobertura, T50, T95, bytes, controle, duplicatas e tempo de recuperação. Não interfere nas decisões dos nós. |
| `src/policies/fanout.py` | Fanout fixo e adaptativo. A política adaptativa usa só estatísticas locais do nó. |
| `src/policies/budget.py` | Orçamento de comunicação por nó e janela de tempo. Cobre mensagens de dados, controle e reparo. |
| `src/policies/peer_selection.py` | Escolha de destinatários; opera sobre a visão local de peers. O sorteio uniforme sem reposição já existe em `Network.sample_peers`; este arquivo só é criado se houver uma política não uniforme. |
| `configs/*.yaml` | Cenários declarativos: duração, nós, topologia, latência, perda, churn, orçamento e parâmetros do protocolo. |
| `configs/tuned.yaml` | Hiperparâmetros congelados de cada variante do DOE, exportados pelo tuning. |
| `experiments/helper.py` | Cola entre simulador e notebook: `run_trial()`, `row_config()`, `run_manifest()` e `summarize_results()`; para o guia de escolha, `factorial_params()`, `pareto_mask()`, `score_conditions()` e `recommend()`. Converte linhas de manifesto em configurações, executa simulações em paralelo e devolve `pandas.DataFrame`s. Não contém lógica de Gossip. |
| `experiments/tuning.py` | Espaço de busca de cada família, função objetivo, restrição, regra de escolha na fronteira de Pareto e `tune_all()`. |
| `experiments/doe.py` | Gera os manifestos CSV do DOE. Não executa simulações. |
| `experiments/notebook.ipynb` | Orquestra validação, estudos Optuna, execução do DOE, gráficos e análise. Não contém a implementação da simulação. |
| `pyproject.toml` | Define o pacote, as dependências e os extras para notebooks e testes. |

## Dependências

As dependências principais bastam para simular. O extra `experiments` traz o que o notebook e a análise usam.

### Dependências principais

| Biblioteca | Uso |
|---|---|
| [SimPy](https://simpy.readthedocs.io/) | Motor de eventos discretos: relógio virtual (`env.now`), processos (`env.process`) e agendamento (`yield env.timeout`). Nada espera em tempo real. |
| [NumPy](https://numpy.org/doc/) | Geradores pseudoaleatórios para sorteio de peers, perdas e latências, com um fluxo de aleatoriedade separado por componente. |
| [NetworkX](https://networkx.org/documentation/stable/) | Gera a topologia regular de grau 8 do DOE (`random_regular_neighbors` em `src/network.py`). A rede completa é implícita e não usa NetworkX. Não simula a transmissão. |
| [PyYAML](https://pyyaml.org/wiki/PyYAMLDocumentation) | Lê os arquivos `configs/*.yaml` usando `yaml.safe_load`. |

### Extra `experiments`

| Biblioteca | Uso |
|---|---|
| [JupyterLab](https://jupyterlab.readthedocs.io/) | Ambiente para editar e executar `experiments/notebook.ipynb`. |
| [ipykernel](https://ipykernel.readthedocs.io/) | Executa o código Python nas células do notebook, usando o ambiente do projeto. |
| [pandas](https://pandas.pydata.org/docs/) | Tabelas de repetições e séries temporais, agregação por protocolo e exportação CSV. |
| [Matplotlib](https://matplotlib.org/stable/) | Figuras de cobertura ao longo do tempo, tráfego e T95. |
| [Seaborn](https://seaborn.pydata.org/) | Gráficos de distribuições e intervalos sobre os DataFrames. |
| [SciPy](https://docs.scipy.org/doc/scipy/) | Estatísticas e estimativas de incerteza, quando adequadas à métrica. |
| [Optuna](https://optuna.readthedocs.io/) | Ajuste de hiperparâmetros em N=50, depois da validação e antes do benchmark final. Usa seeds de treino distintas das seeds do DOE. |

### Desenvolvimento e empacotamento

| Ferramenta | Uso |
|---|---|
| [pytest](https://docs.pytest.org/) (`dev`) | Testes determinísticos dos protocolos, do transporte, do orçamento e da reprodutibilidade. |
| [Hatchling](https://hatch.pypa.io/) (`build-system`) | Instala o código local em modo editável, para o notebook importar `src` sem mexer no `sys.path`. |
| [uv](https://docs.astral.sh/uv/) | Gerencia Python, ambiente virtual, dependências e lockfile. Ferramenta externa, não é dependência Python do projeto. |

Docker, gRPC, Prometheus, OpenTelemetry e `netem` não são usados: falhas e atrasos são eventos simulados.

## Fluxo experimental

O tuning com Optuna ocorre depois da implementação e da validação dos algoritmos, e antes do benchmark definitivo. A página 5 do PDF prevê Optuna em N=50 com o mesmo número de tentativas por protocolo.

As seis etapas do fluxo, em ordem de execução:

| Etapa | Conteúdo |
|---|---|
| 1. Implementação | Push, Push-Pull, anti-entropy, fanout adaptativo e métricas |
| 2. Validação | Testes de corretude e comparação com o modelo analítico |
| 3. Tuning com Optuna | N=50, seeds de treino, orçamento fixo, mesmo número de trials por família |
| 4. Congelamento dos parâmetros | Exportar a configuração escolhida de cada família para `configs/tuned.yaml` |
| 5. DOE (benchmark definitivo) | N=50–500, churn, perda, latência, partições, seeds de teste. Depois, varredura de escala em N=1.000, 10.000 e 100.000 |
| 6. Análise estatística | Cobertura × T95 × tráfego, intervalos de confiança, trade-offs |
| 7. Guia de escolha | Fatorial dos mecanismos com parâmetros comuns, recomendação por prioridade e validação em condições novas |

### Papel do DOE e do Optuna

Objetivo, fatores variados, resultado e momento de cada etapa:

| | DOE | Optuna |
|---|---|---|
| Objetivo | Avaliar os algoritmos em diferentes condições | Encontrar bons hiperparâmetros |
| Varia | Cenários, perda, churn, N, latência, orçamento | Fanout, intervalos, thresholds |
| Resultado | Evidência experimental e comparação | Configuração otimizada |
| Quando | Benchmark final | Depois da implementação, antes do benchmark final |

### Hiperparâmetros ajustados

Hiperparâmetros que o Optuna ajusta em cada família de protocolo, com o espaço de busca de cada um:

| Família | Hiperparâmetro | Espaço de busca |
|---|---|---|
| Push, Push-Pull, Push + AE | `fanout` | inteiro, 1 a 5 |
| Push, Push-Pull, Push + AE | `gossip_interval_ms` | 250, 500 ou 1.000 |
| Push + AE, Adaptativo + AE | `ae_interval_ms` | 1.000, 2.000 ou 5.000 |
| Adaptativo + AE | `min_fanout` | inteiro, 1 a 2 |
| Adaptativo + AE | `max_fanout` | inteiro, 3 a 5 |
| Adaptativo + AE | `duplicate_threshold` | real, 0,1 a 0,9 |
| Adaptativo + AE | `timeout_threshold` | real, 0,1 a 0,9 |
| Adaptativo + AE + quiescência | `quiescence_rounds` | grade, 1 a 10 |

- `gossip_interval_ms` corresponde a `simulation.gossip_interval_ms` em `configs/baseline.yaml`. No Adaptativo + AE ele fica fixo em 500 ms.
- `fanout` corresponde a `protocol.fanout` e `ae_interval_ms` a `protocol.ae_interval_ms` (`null` = sem anti-entropy). A família é escolhida por `protocol.name` (`push` ou `push_pull`).
- `min_fanout`, `max_fanout`, `duplicate_threshold`, `timeout_threshold` e `quiescence_rounds` ficam em `protocol.adaptive`. Com `protocol.adaptive: null`, o fanout é fixo.
- `duplicate_threshold`: fração de `DATA` duplicadas, entre as `DATA` recebidas pelo nó desde a rodada anterior, acima da qual o nó reduz o fanout em 1.
- `timeout_threshold`: fração de trocas de anti-entropy com timeout, entre as 5 últimas trocas do nó, acima da qual o nó aumenta o fanout em 1.

O orçamento de bytes por nó e janela é uma restrição experimental. O Optuna não o ajusta, porque aumentar o orçamento melhoraria o desempenho sem medir a qualidade do algoritmo.

### Fanout adaptativo

Cada nó tem um fanout atual, entre `min_fanout` e `max_fanout`. A política está em `src/policies/fanout.py` (`AdaptiveFanout`) e usa só estatísticas locais: as `DATA` que o nó recebeu e o resultado das trocas de anti-entropy que ele iniciou.

| Item | Definição |
|---|---|
| Valor inicial | `max_fanout`. A disseminação começa rápida, e o fanout cai quando o nó observa duplicatas. |
| Redução | A cada rodada de gossip, o nó calcula a fração de duplicatas entre as `DATA` recebidas desde a rodada anterior. Se a fração passa de `duplicate_threshold`, o fanout diminui 1, até `min_fanout`. Uma rodada sem `DATA` recebida não altera o fanout. |
| Aumento | Quando o resultado de uma troca de anti-entropy fica conhecido (resposta ou timeout), o nó calcula a fração de timeouts nas suas 5 últimas trocas (`TIMEOUT_WINDOW`). Se a fração passa de `timeout_threshold`, o fanout aumenta 1, até `max_fanout`. |
| Momento das regras | Cada regra é avaliada quando chega informação nova para ela: a de duplicatas a cada rodada de gossip, a de timeouts a cada troca de anti-entropy. |
| Intervalo de gossip | Fixo em 500 ms. |
| Churn | Um nó offline mantém o fanout atual e a janela de trocas. |

A janela de 5 trocas é uma escolha deste projeto. Com `ae_interval_ms` de 1.000 a 5.000 ms, ela cobre de 5 a 25 s.

### Quiescência após saturação local

No plano original do PDF, não há mecanismo para fazer os nós pararem de enviar mensagens. No Push, um nó que possui a atualização envia em todas as rodadas até `duration_ms`. Em `adaptive_ae`, o fanout varia entre 1 e 5, então o mínimo ainda é uma mensagem por rodada. O orçamento limita os bytes por janela, mas não suspende a disseminação.

A extensão suspende o Push de uma atualização quando o nó observa saturação local, e mantém a anti-entropy periódica.

Cada nó tem dois estados por atualização, ativo e quiescente, e um contador `saturation_count`. Um nó sem a atualização não envia `DATA` e não participa dessa máquina de estados.

| Item | Definição |
|---|---|
| Mecanismo | No estado quiescente, a política de fanout devolve 0. A anti-entropy continua nos dois estados. Fica em `src/policies/fanout.py`; não há módulo novo. O estado quiescente é `saturation_count >= quiescence_rounds`; não há indicador separado. |
| Evidência de saturação | Desde a rodada anterior, o nó recebeu pelo menos uma `DATA` duplicada, ou concluiu uma troca de anti-entropy em que o peer tinha a mesma versão. As duas são estatísticas locais e não exigem mensagens extras. |
| Contagem | A cada rodada de gossip com evidência, `saturation_count` aumenta 1. Uma rodada sem evidência não zera o contador. |
| Entrada na quiescência | `saturation_count` atinge `quiescence_rounds`. |
| Retomada do Push | O nó recebe uma versão mais nova, ou uma troca de anti-entropy mostra um peer com versão mais antiga. O contador volta a 0 e o nó volta ao estado ativo. |
| Timeouts | Não contam como evidência e não zeram o contador. Um peer sem resposta pode estar offline ou do outro lado de uma partição. |
| Churn | Um nó que fica offline mantém o estado e o contador. |
| Dependência | Só é usada em variantes com anti-entropy. Push com parada deixa uma fração de nós sem a atualização (Demers et al., "Epidemic Algorithms for Replicated Database Maintenance", 1987); a anti-entropy recupera esses nós. |
| Tuning | `quiescence_rounds`, em grade de 1 a 10, com os parâmetros de `adaptive_ae` congelados. |

A quiescência é uma heurística. As duas evidências indicam que a atualização é comum na vizinhança do nó, mas não provam que todos os peers a têm. O DOE mede o erro dessa heurística pela cobertura, pelo T95 e pelo `recovery_ms` de `adaptive_ae_quiescent` contra `adaptive_ae`.

A evidência por anti-entropy não pode ser removida. Só com duplicatas de Push, os últimos nós ativos deixariam de receber duplicatas, porque os peers já quiescentes não enviam `DATA`, e nunca entrariam em quiescência. Pelo mesmo motivo, uma rodada sem evidência não zera o contador.

A quiescência entra no DOE como ablação do fanout adaptativo, com uma única variante, `adaptive_ae_quiescent`. Ela difere de `adaptive_ae` somente pela quiescência.

O tráfego total das variantes sem quiescência cresce com `duration_ms`, porque elas enviam até o fim. Por isso as métricas também reportam os bytes enviados até T95.

Itens fora do escopo:

- Intervalo de gossip adaptativo (estado intermediário com fanout reduzido e intervalo maior). Seria uma segunda variante de ablação.
- Feedback explícito por ACK do destinatário.
- Seleção de peers que priorize quem ainda não confirmou a atualização.
- Regra de parada para os baselines de Push estático.

### Função objetivo

O estudo minimiza T95 e tráfego em bytes, sujeito a cobertura de pelo menos 95% e ao orçamento de comunicação. O simulador aplica o orçamento (`src/policies/budget.py`). A cobertura mínima entra como restrição do estudo Optuna.

O estudo é multiobjetivo: o resultado de cada família é uma fronteira de Pareto entre T95 e tráfego, sem combinar as duas métricas em um único número por pesos arbitrários.

Cada trial executa 30 simulações em N=50: 3 cenários (`stable`, `loss_5pct`, `churn_10pct`) × 10 seeds de treino.

| Item | Definição |
|---|---|
| Objetivo 1 | Média de `t95_ms` nas 30 simulações. Uma simulação sem T95 entra com `duration_ms` (60.000). |
| Objetivo 2 | Média de `bytes_total` nas 30 simulações. |
| Restrição | As 30 simulações atingem 95% de cobertura. Um trial que viola a restrição é inviável. |

O objetivo 2 usa `bytes_total` e não `bytes_until_t95`. A quiescência só reduz os bytes enviados depois da saturação; com `bytes_until_t95`, `quiescence_rounds` quase não alteraria o objetivo.

A etapa de congelamento exige uma única configuração por família. A regra de escolha fica fixada antes do tuning, para não depender dos resultados do DOE:

1. Considerar somente os trials viáveis da fronteira de Pareto da família.
2. Normalizar cada objetivo entre 0 e 1 pelo mínimo e pelo máximo dessa fronteira.
3. Escolher o trial com a menor distância euclidiana ao ponto (0, 0). Em empate, o de menor `bytes_total`.
4. Se a família não tiver trial viável, escolher o trial com mais simulações que atingiram 95% e registrar o fato no relatório.

### Separação entre tuning e avaliação

- As seeds de treino do tuning devem ser disjuntas das seeds do piloto (100..109) e das seeds de teste do DOE (1000..1029), ambas definidas em `experiments/doe.py`.
- Os parâmetros congelados em `configs/tuned.yaml` não são reajustados depois de observar os resultados do DOE.
- O tuning ocorre somente em N=50. O DOE executa os mesmos parâmetros em N=100, 250 e 500, o que mede se a configuração ajustada, em particular o fanout adaptativo, mantém o desempenho em redes maiores. A varredura de escala repete a medida em N=1.000, 10.000 e 100.000, sem novo tuning.

### Regras do tuning

| Item | Regra |
|---|---|
| Seeds de treino | 0..9 |
| Trials | 30 por família, nas quatro famílias do PDF (Push, Push-Pull, Push + AE, Adaptativo + AE) |
| Amostrador | `optuna.samplers.TPESampler(seed=0)` com a restrição de cobertura |
| Rede | N=50, topologia regular de grau 8, 60 s, como no DOE |
| Cenários | `stable`, `loss_5pct`, `churn_10pct` |
| Orçamento | 4.096 bytes por nó a cada 1.000 ms, fixo |
| Agregação | Média sobre as 30 simulações do trial |
| Custo | 4 famílias × 30 trials × 30 simulações = 3.600 simulações em N=50, mais 300 da grade de quiescência |

Ablação da quiescência: `adaptive_ae_quiescent` usa os parâmetros congelados de `adaptive_ae`. Só `quiescence_rounds` é escolhido, por uma grade de 1 a 10 avaliada com os mesmos cenários, seeds, objetivos e regra de escolha. Assim, a diferença entre as duas variantes no DOE vem só da quiescência.

Uso dos parâmetros congelados no DOE:

| Variante do DOE | Origem dos hiperparâmetros |
|---|---|
| `push_f1` | Fixos: fanout 1, intervalo de 500 ms. Baseline sem tuning, igual ao da validação analítica. |
| `push_tuned` | `configs/tuned.yaml`, família Push |
| `push_pull` | `configs/tuned.yaml`, família Push-Pull |
| `push_ae` | `configs/tuned.yaml`, família Push + AE |
| `adaptive_ae` | `configs/tuned.yaml`, família Adaptativo + AE |
| `adaptive_ae_quiescent` | Os de `adaptive_ae`, mais `quiescence_rounds` |

`push_tuned` substitui o antigo `push_f3`. O PDF pede o mesmo número de tentativas por protocolo; comparar o adaptativo ajustado só com um Push sem ajuste favoreceria o adaptativo. O fanout 3 continua na validação analítica (seção 2 do notebook).

## Especificação do modelo

Regras de mensagens, falhas, orçamento e métricas. `src/` implementa todas as regras desta seção, exceto `wall_time_s`, que é medido em `experiments/helper.py`. Os diagramas de estados (churn, caminho de uma mensagem e quiescência) estão em <https://claude.ai/artifact/XyksbJC62AGpVtbRr3LHFe>, página privada do autor do projeto.

### Mensagens e protocolos

Há dois tipos de mensagem. O cabeçalho tem 16 bytes.

| Tipo | Conteúdo | Tamanho | Categoria de bytes |
|---|---|---|---|
| `DATA` | A atualização: versão e payload | 16 + `update.size_bytes` = 272 bytes | Dados. Reparo, quando responde a um `DIGEST`. |
| `DIGEST` | Só a versão do remetente | 16 bytes | Controle |

Trocas de mensagens de cada protocolo:

| Protocolo | Troca |
|---|---|
| Push | A cada rodada, um nó com a atualização envia `DATA` a `fanout` peers. |
| Push-Pull | A cada rodada, todo nó contata `fanout` peers. Com a atualização, envia `DATA`. Sem ela, envia `DIGEST`, e o peer responde `DATA` se tiver a atualização. |
| Anti-entropy | A cada `ae_interval_ms`, todo nó envia `DIGEST` a 1 peer. O peer responde `DATA` se tiver versão mais nova; senão, responde `DIGEST` com a própria versão. Se a versão respondida for mais antiga que a do iniciador, o iniciador envia `DATA`. |

Uma troca de anti-entropy sem resposta até o próximo tick de anti-entropy do iniciador conta como timeout. Push e Push-Pull não geram timeouts.

- A resposta que conclui a troca é um `DATA` ou `DIGEST` de anti-entropy vindo do peer contatado. Um `DATA` de Push vindo do mesmo peer não conclui a troca.
- Um `DIGEST` de anti-entropy barrado pelo orçamento do iniciador não abre uma troca e não gera timeout.
- Um pedido do Push-Pull a um peer sem a atualização fica sem resposta.

No código (`src/protocols.py`), `Message` tem o campo `kind` (`"DATA"` ou `"DIGEST"`) e dois indicadores: `reply`, verdadeiro em toda resposta a um `DIGEST`, e `ae`, verdadeiro nas mensagens de uma troca de anti-entropy. Um `DATA` com `reply` verdadeiro é um reparo. `PushPull` herda de `Push` e só muda a rodada do nó sem a atualização. A anti-entropy é o método `on_ae_round`, ativado por `protocol.ae_interval_ms`.

### Latência e perda

- Latência: inteiro uniforme em `[latency_min_ms, latency_max_ms]`, sorteado por mensagem. A latência máxima do DOE (200 ms) é menor que o menor intervalo de gossip (250 ms).
- Perda: cada mensagem, de qualquer tipo, é perdida com probabilidade `packet_loss`, de forma independente. O sorteio usa um gerador aleatório próprio. A mensagem perdida conta nos bytes enviados e no orçamento.

### Churn

- `churn_fraction` é a fração de nós offline em todo instante: a parte inteira de `churn_fraction × N` (2 nós em N=50 com 5%).
- Em t=0 e a cada `churn_period_ms` (5.000 ms), o conjunto offline é sorteado de novo, de modo uniforme. O conjunto anterior volta a ficar online.
- O nó de origem da atualização nunca fica offline. Sem essa regra, T50 e T95 mediriam a espera pelo retorno da origem em parte das execuções.
- Um nó offline não executa rodadas de gossip nem de anti-entropy, e as mensagens que chegam a ele são descartadas.
- Um nó offline mantém o estado: versão, contadores e estado de quiescência. Ao voltar, continua de onde parou.
- A visão de peers é estática. Não há detector de falhas, e os nós continuam sorteando peers offline.
- O churn usa um gerador aleatório próprio. A mesma seed produz o mesmo cronograma de churn em todas as variantes.

### Partição

- Dois grupos, definidos por `node_id % 2`.
- A partição fica ativa de `partition_start_ms` = 0 até `partition_end_ms` = 20.000.
- A partição começa junto com a injeção da atualização. Com início em 10 s, a atualização já teria chegado a todos os nós: medido com Push de fanout 1 em rede completa, a cobertura total ocorreu até 7 s em N=50 e até 9 s em N=500 (20 seeds).

### Regra de entrega

Uma mensagem enviada é entregue se as três condições valem no instante da entrega:

1. A mensagem não foi sorteada como perdida.
2. O destinatário está online.
3. Não há partição ativa, ou remetente e destinatário estão no mesmo grupo.

Caso contrário, a mensagem é descartada e o remetente não é avisado. Uma mensagem enviada por um nó que fica offline depois do envio é entregue normalmente.

No mesmo instante simulado, as mudanças de estado da rede (churn, início e fim da partição) são aplicadas antes das entregas e das rodadas.

### Orçamento

- Janelas fixas de `budget.interval_ms` (1.000 ms), alinhadas a múltiplos de 1.000 ms, por nó.
- Toda mensagem é cobrada no envio, pelo tamanho: `DATA` e `DIGEST`, incluindo respostas e reparos.
- Uma mensagem que não cabe no saldo da janela não é enviada e não fica em fila. Ela conta em `budget_drops`.
- O saldo é consumido na ordem dos envios dentro da janela.
- `Network.send` consulta `Budget.try_spend` (`src/policies/budget.py`) antes de contar os bytes e de sortear a perda. Uma mensagem barrada não entra em `bytes_total`.
- Uma `DATA` tem 272 bytes: o orçamento de 4.096 bytes permite 15 `DATA` por nó a cada janela, e o de 2.048 permite 7. Com rodadas de 500 ms, há duas rodadas por janela; a primeira usa o saldo antes da segunda.

### Métricas

| Coluna do `summary_df` | Definição |
|---|---|
| `coverage_final` | Cobertura em `duration_ms`. |
| `t50_ms`, `t95_ms` | Primeiro instante em que a cobertura atinge 50% e 95%, contado da injeção (t=0). `NaN` se não ocorrer até `duration_ms`. |
| `bytes_total` | Soma dos tamanhos de todas as mensagens enviadas, inclusive as perdidas e as descartadas na entrega. |
| `bytes_until_t95` | Mesma soma, só para envios até `t95_ms`. `NaN` se `t95_ms` for `NaN`. |
| `bytes_control` | Bytes de `DIGEST`. O overhead de controle é `bytes_control / bytes_total`. |
| `bytes_repair` | Bytes de `DATA` enviadas em resposta a um `DIGEST`. |
| `duplicates` | `DATA` entregues a um nó que já tinha aquela versão ou uma mais nova. |
| `timeouts` | Trocas de anti-entropy sem resposta. |
| `budget_drops` | Mensagens não enviadas por falta de saldo. |
| `recovery_ms` | Só no cenário de partição: `t95_ms − partition_end_ms`. `NaN` nos demais cenários ou sem T95. |
| `wall_time_s` | Tempo real da execução, em segundos. |

Cobertura e coorte elegível:

- A coorte elegível no instante t são os nós online em t. A cobertura é a fração da coorte que tem a atualização.
- Sem churn, a coorte são os N nós. A partição não altera a coorte.
- Com churn, a cobertura pode cair quando nós sem a atualização voltam a ficar online. T50 e T95 são a primeira travessia do limiar; as quedas aparecem no `coverage_df`.
- O `coverage_df` amostra a cobertura a cada 500 ms, em qualquer variante.
- No cenário de partição, o grupo sem a origem só recebe a atualização depois de 20 s. A cobertura fica limitada a cerca de 50% até lá, e T95 ocorre depois da reconexão. A métrica do cenário é `recovery_ms`.

As métricas usam contadores agregados e os instantes da primeira recepção de cada nó. Não há registro por mensagem.

Toda execução roda até `duration_ms`. Não há parada antecipada quando a cobertura chega a 100%, para que `bytes_total` seja comparável entre variantes.

## Interface entre notebook e simulador

Interface pública de `experiments/helper.py`:

```python
def run_trial(config: dict, seed: int) -> tuple[dict, pd.DataFrame]:
    """Executa uma simulação.

    Retorna a linha de resumo e a curva de cobertura dessa execução.
    """

def row_config(row, params: dict) -> dict:
    """Configuração de uma linha do manifesto, com os hiperparâmetros da variante."""

def run_manifest(plan: pd.DataFrame, tuned: dict, out=None, workers=None
                 ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Executa cada linha de um manifesto do DOE.

    Retorna (summary_df, coverage_df).
    """

def summarize_results(summary_df: pd.DataFrame, by=("scenario", "protocol_variant")
                      ) -> pd.DataFrame:
    """Agrega por cenário e variante: medianas, quartis de T95 e fração de
    execuções que atingiram T95."""

def factorial_params(row, tuned: dict) -> dict:
    """Hiperparâmetros comuns de uma linha do fatorial (`fanout_value` "common")."""

def pareto_mask(values) -> np.ndarray:
    """True nas linhas que nenhuma outra domina (todas as colunas a minimizar)."""

def score_conditions(summary_df, by=("scenario", "n_nodes")) -> pd.DataFrame:
    """Medianas de T95 e bytes por condição e combinação, viabilidade, fronteira
    de Pareto e pontuação de cada prioridade (0 = melhor da condição)."""

def recommend(scored, by=("scenario", "n_nodes")) -> dict:
    """Combinação de menor pontuação média por prioridade, entre as viáveis em
    todas as condições."""
```

- Linhas com `fanout_value` igual a `common` (os manifestos `doe_factorial.csv` e `doe_validation.csv`) recebem os hiperparâmetros de `factorial_params`; as demais, os de `tuned[protocol_variant]`.

- `tuned` associa cada variante aos seus hiperparâmetros: o conteúdo de `configs/tuned.yaml`. `push_f1` é fixo (fanout 1, 500 ms) e não precisa estar em `tuned`.
- `row_config` confere, com `assert`, que os hiperparâmetros correspondem ao tratamento descrito na linha do manifesto (`anti_entropy`, `fanout_policy`, `quiescence`).
- `run_manifest` executa as linhas em paralelo, um processo por núcleo (`workers`). Com `out` (prefixo de arquivo), grava `<out>_summary.csv` e `<out>_coverage.csv.gz` a cada 60 s e, em uma nova chamada, só executa as linhas que faltam.
- Pela linha de comando: `python experiments/helper.py experiments/doe/doe_pilot.csv` grava em `results/doe_pilot_*`.

`run_manifest` chama `run_trial`, e a função objetivo de `experiments/tuning.py` chama `run_manifest` sobre as linhas de N=50 de `doe_design.csv`. Assim, o tuning e o DOE executam o mesmo código de simulação e as mesmas definições de cenário.

As variantes diferem só no protocolo e nas políticas. A rede simulada é a mesma.

`summary_df` tem uma linha por execução, com as colunas:

```text
run_id, scenario, protocol_variant, seed, n_nodes, coverage_final,
t50_ms, t95_ms, bytes_total, bytes_until_t95, bytes_control, bytes_repair,
duplicates, timeouts, budget_drops, recovery_ms, wall_time_s
```

`wall_time_s` é o tempo real da execução, em segundos. Mede o custo do simulador, não do protocolo, e é usado na varredura de escala.

`coverage_df` tem várias linhas por execução, com as colunas:

```text
run_id, scenario, protocol_variant, seed, time_ms, coverage
```

`run_id` e `protocol_variant` vêm do manifesto do DOE. A coluna `protocol` do manifesto não distingue os tratamentos: ela vale `push` em `push_f1`, `push_tuned`, `push_ae`, `adaptive_ae` e `adaptive_ae_quiescent`. Os demais fatores do manifesto, como o orçamento, são obtidos por junção em `run_id`.

`coverage` é uma fração entre 0 e 1 sobre a coorte elegível. `t95_ms` é `NaN` se a execução não atingir 95% até o horizonte da simulação; essas execuções não são excluídas. A seção "Especificação do modelo" define cada coluna.

## Organização do `experiments/notebook.ipynb`

Seções do notebook, na ordem de execução:

1. Imports e configuração: hipóteses em Markdown, `yaml.safe_load` de `configs/baseline.yaml`, seeds de treino e número de trials.
2. Validação do simulador: rede completa sem falhas, N=100, fanout 1 e 3; comparar a curva Push com o modelo analítico.
3. Tuning com Optuna em N=50: um estudo por família de protocolo, com o mesmo número de trials e a função objetivo de `experiments/tuning.py`.
4. Exportação dos parâmetros: gravar a configuração escolhida de cada família em `configs/tuned.yaml`.
5. Carregamento do DOE: ler os manifestos de `experiments/doe/`, incluindo `doe_scale.csv`.
6. Piloto e benchmark completo: `run_manifest` sobre `doe_pilot.csv`, depois sobre `doe_runs.csv` e por último sobre `doe_scale.csv`; conferir total de execuções, valores ausentes e execuções sem T95.
7. Análise estatística e gráficos: tabelas por cenário, cobertura × tempo, T95 × tráfego, efeito de N; comparação pareada com teste de Wilcoxon (7.1), interação perda × churn (7.2), orçamento (7.3), varredura de escala de N=50 a 100.000 (7.4), ablação da quiescência e recuperação após a partição (7.5), efeito de cada fator de ambiente (7.6).
8. Guia de escolha de mecanismos: importância dos hiperparâmetros (8.1), fatorial dos mecanismos com efeitos em T95, bytes e DATA duplicadas (8.2), fronteira de Pareto e recomendação por prioridade (8.3), validação em condições novas (8.4).
9. Conclusões: resposta à hipótese, casos em que o adaptativo perde, guia de escolha e limitações.

O notebook define os estudos Optuna e os gráficos. A simulação fica em `src/` e é chamada por `experiments/helper.py`.

Todas as células executam. As etapas longas guardam os resultados em `results/` e não repetem o que já foi feito: os estudos Optuna ficam em `results/tuning.db`, e cada manifesto em `results/<manifesto>_summary.csv` e `results/<manifesto>_coverage.csv.gz`. Com esses arquivos presentes, o notebook inteiro executa em poucos minutos.

### Interface de `experiments/tuning.py`

```python
FAMILIES = ("push_tuned", "push_pull", "push_ae", "adaptive_ae")

def objective(trial, family, seeds, frozen=None, workers=None) -> tuple[float, float]:
    """Média de T95 e média de bytes nas simulações do trial."""

def constraints(trial) -> tuple[int]:
    """Viável se todas as simulações atingem 95% (valor <= 0)."""

def select_trial(study) -> pd.DataFrame:
    """Tabela dos trials, com as colunas `pareto` e `selected` (regra do README)."""

def tune_all(n_trials, seeds, workers=None) -> tuple[dict, dict]:
    """Roda os quatro estudos e a grade de quiescência. Devolve (tuned, trials)."""
```

- As famílias têm o nome da variante do DOE que usa os parâmetros. A família Push do PDF é `push_tuned`.
- Os quatro estudos usam `optuna.samplers.TPESampler(seed=0, constraints_func=constraints)`. O NSGA-II padrão, com população 50, faria só amostragem aleatória em 30 trials.
- A grade de `quiescence_rounds` usa `optuna.samplers.GridSampler`, com os parâmetros de `adaptive_ae` passados em `frozen`.
- Pela linha de comando: `python experiments/tuning.py` roda tudo e grava `configs/tuned.yaml`.

## Reprodutibilidade e comparações justas

- Mesmo cenário e mesmo orçamento de bytes por nó e intervalo para todos os protocolos, incluindo anti-entropy e controle.
- Seeds registradas e separadas por componente: topologia, falhas e latência são as mesmas entre tratamentos com a mesma seed, e o gerador aleatório de um componente não consome o de outro.
- Mesmo horizonte e mesma definição de coorte e cobertura. Reportar execuções que não convergem e execuções sem T95.
- Validar primeiro em rede completa sem falhas. Depois adicionar atraso, perda e churn, um de cada vez.
- Rodar várias seeds e apresentar a dispersão, não só a média.
- Optuna: ajustar em N=50 com seeds de treino disjuntas das seeds do piloto e do DOE, mesmo número de trials por família e orçamento fixo. Não reajustar os parâmetros depois de ver os resultados do DOE.
- Salvar resultados brutos, configuração, seed e versão do código. Não commitar arquivos de saída grandes.

## Resultados

Resumo de `experiments/notebook.ipynb`, que traz as tabelas completas, os gráficos e os testes estatísticos. Os números são medianas. Salvo indicação, valem para N=100 e orçamento de 4.096 bytes, com 30 seeds. As razões são medianas de pares com o mesmo cenário, N, orçamento e seed.

Volume executado: 3.900 simulações de tuning, 600 do piloto, 17.640 do DOE e 540 da varredura de escala. Todas as execuções do DOE e da varredura atingiram 95% de cobertura e terminaram com cobertura 1,0.

Parâmetros congelados em `configs/tuned.yaml`, escolhidos em N=50:

| Variante | Parâmetros |
|---|---|
| `push_f1` | fanout 1, rodada a cada 500 ms (fixo, sem tuning) |
| `push_tuned` | fanout 1, rodada a cada 250 ms |
| `push_pull` | fanout 2, rodada a cada 500 ms |
| `push_ae` | fanout 1, rodada a cada 250 ms, anti-entropy a cada 1.000 ms |
| `adaptive_ae` | fanout de 1 a 3, `duplicate_threshold` 0,38, `timeout_threshold` 0,68, anti-entropy a cada 2.000 ms |
| `adaptive_ae_quiescent` | os de `adaptive_ae`, com `quiescence_rounds` 1 |

Cenário estável:

| Variante | T95 (ms) | Bytes até T95 (kB) | Bytes em 60 s (MB) |
|---|---|---|---|
| `push_f1` | 5.510 | 102 | 3,04 |
| `push_tuned` | 2.760 | 102 | 6,30 |
| `push_pull` | 2.020 | 94 | 6,35 |
| `push_ae` | 2.030 | 78 | 6,54 |
| `adaptive_ae` | 2.510 | 114 | 3,32 |
| `adaptive_ae_quiescent` | 2.510 | 80 | 0,20 |

Razão pareada `adaptive_ae / baseline`, faixa nos nove cenários sem partição (abaixo de 1, o adaptativo é melhor):

| Baseline | T95 | Bytes em 60 s |
|---|---|---|
| `push_f1` | 0,41 a 0,45 | 1,10 a 1,13 |
| `push_tuned` | 0,86 a 0,89 | 0,53 a 0,54 |
| `push_pull` | 1,20 a 1,24 | 0,52 a 0,53 |
| `push_ae` | 1,07 a 1,15 | 0,51 a 0,52 |

Conclusões:

- A hipótese vale em parte. `adaptive_ae` envia cerca de metade dos bytes das três famílias de fanout fixo ajustadas e é mais rápido que o Push ajustado. Ele é mais lento que Push-Pull (cerca de 500 ms, uma rodada) e que Push + AE; a diferença é significativa em todos os cenários (Wilcoxon pareado, p < 1e-21).
- A economia vem do tráfego depois da saturação. Até T95, todas as variantes gastam entre 0,75 e 1,3 kB por nó, de N=50 a N=100.000. A razão de 0,5 nos bytes totais depende do horizonte de 60 s.
- Perda e churn juntos (perda de 1% a 10%, churn de 5% a 20%) não mudam as razões entre variantes. Em N=500, T95 de `adaptive_ae` vai de 3.510 a 4.010 ms entre a combinação mais leve e a mais pesada; o de `push_tuned`, de 3.760 a 4.760 ms.
- O orçamento não diferenciou as variantes. Com 4.096 bytes nenhuma mensagem foi barrada. Com 2.048 bytes houve mensagens barradas em 91% das execuções de `adaptive_ae`, sem efeito em T95 ou nos bytes.
- Escala: T95 cresce de forma linear com log N. No cenário estável, de N=50 a N=100.000, `push_f1` vai de 5.010 a 11.760 ms e `adaptive_ae` de 2.020 a 5.010 ms. A razão de bytes de `adaptive_ae` contra `push_tuned` é 0,53 em N=1.000, 10.000 e 100.000.
- Quiescência: `adaptive_ae_quiescent` envia de 6% a 8% dos bytes de `adaptive_ae`, com T95 de 4% a 17% maior no DOE principal e até 33% maior na varredura de escala. Cobertura final e recuperação após a partição são iguais.
- Recuperação após a partição (`recovery_ms`): `push_pull` 20 ms, `push_ae` 260 ms, `adaptive_ae` e `adaptive_ae_quiescent` 510 ms, `push_tuned` 760 ms, `push_f1` 1.510 ms, iguais de N=50 a 500. O valor de `push_pull` depende de a reconexão coincidir com uma rodada.

A seção 9 do notebook lista os casos em que o adaptativo perde e as limitações do estudo.

## Guia de escolha de mecanismos

Pergunta: como escolher, de forma sistemática, os mecanismos de Gossip para uma condição de rede e uma prioridade? O passo a passo, implementado na seção 8 do notebook:

1. Métricas: T95 e bytes em 60 s, os objetivos do tuning. Uma combinação é viável numa condição se todas as execuções atingem 95% de cobertura. DATA duplicadas explicam de onde vêm os bytes.
2. Importância dos hiperparâmetros contínuos nos trials do tuning (PED-ANOVA do Optuna).
3. Fatorial dos mecanismos: disseminação (Push, Push-Pull) × fanout (fixo, adaptativo) × anti-entropy (não, sim) × quiescência (não, sim; só com fanout adaptativo) = 12 combinações. Todas usam os mesmos parâmetros (`helper.factorial_params`): rodada de 500 ms, fanout fixo 2, anti-entropy a cada 1.000 ms, e no adaptativo os limiares e `quiescence_rounds` de `configs/tuned.yaml`. `doe_factorial.csv`: estável, perda 5%, churn 10% e partição × N=100 e 500 × 30 seeds = 2.880 execuções.
4. Fronteira de Pareto por condição e recomendação por prioridade. Pontuação em cada condição, 0 = a melhor: `latency` e `traffic` são o excesso relativo de T95 e de bytes; `balanced` é a distância a (0, 0) com os dois objetivos normalizados, a regra do tuning. A recomendação é a combinação de menor pontuação média entre as viáveis em todas as condições.
5. Validação em condições que não entraram no passo 4. `doe_validation.csv`: latência de 10 a 200 ms e perda de 10% com churn de 20% em N=250, churn de 20% em N=1.000, estável em N=10.000, × 12 combinações × 30 seeds = 1.440 execuções.

Efeito de cada mecanismo, mediana das razões pareadas (com / sem) nas 6 condições do fatorial sem partição:

| Mecanismo | T95 | Bytes em 60 s |
|---|---|---|
| Push-Pull | 0,50 a 0,83 | 1,01 a 1,09 (1,12 a 1,39 com quiescência sem anti-entropy) |
| Fanout adaptativo (1 a 3) contra fixo 2 | 0,75 a 0,86 (0,99 em um caso) | 0,52 a 0,53 |
| Anti-entropy | 0,71 a 0,86 no Push; 1,00 no Push-Pull | 1,03 a 1,07; 0,28 a 0,38 com quiescência |
| Quiescência, com anti-entropy | 1,00 no Push-Pull; até 1,20 no Push | 0,08 a 0,09 |

Push com quiescência e sem anti-entropy é a única combinação inviável: na partição, 5% das execuções não atingem T95 e a cobertura final mínima é 0,006.

Guia, montado com as 8 condições do fatorial e validado nas 4 condições novas:

| Prioridade | Combinação | Fatorial | Validação |
|---|---|---|---|
| Latência | `push_pull_adaptive_ae` | menor T95 nas 8 condições (empata com `push_pull_adaptive` em 7) | menor T95 nas 4 |
| Tráfego | `push_adaptive_ae_q` | menos bytes nas 8 | menos bytes em 3; 0,4% acima da melhor com perda de 10% e churn de 20% |
| Equilíbrio | `push_pull_adaptive_ae_q` | a melhor nas 8; T95 igual ao menor em 7, com 2% a 8% mais bytes que a mais barata sem partição | a melhor nas 4 |

No cenário estável em N=100, `push_pull_adaptive_ae_q` tem T95 de 1.520 ms e 0,29 MB em 60 s; o `push_pull` ajustado da seção 7 tem 2.020 ms e 6,35 MB.

Limites: os parâmetros comuns não foram ajustados para cada combinação; o guia cobre topologia regular de grau 8 e uma única atualização; a pontuação usa uma regra fixa, e empates de T95 são frequentes porque T95 é medido em múltiplos da rodada.

No Push-Pull, o nó sem a atualização chama `policy.fanout` para escolher quantos peers consultar. A quiescência só vale para nós com a atualização (`AdaptiveFanout.fanout`); sem essa condição, uma troca de anti-entropy entre dois nós sem a atualização voltava "same" e parava o pull. A mudança não altera as execuções do Push: o piloto de 600 execuções é idêntico antes e depois.

## Implementação (timeline)

Estado em 19/11/2026: os dez itens estão feitos. O código de `src/` e de `experiments/` tem 53 testes (`tests/`). Os resultados estão em `experiments/notebook.ipynb`.

1. `simulation.py` + `network.py` + `protocols.py`: Push simples, sem falhas, um evento versionado. Feito: rede completa implícita, latência uniforme em ms inteiros, fanout fixo, sorteio uniforme de peers sem reposição, um gerador aleatório por componente (rede, protocolo, injeção).
2. `metrics.py`: as colunas definidas em "Especificação do modelo", com contadores agregados. Um registro por mensagem não cabe na memória em N=100.000 (10 milhões de mensagens por execução). Feito: `coverage_final`, `t50_ms`, `t95_ms`, `bytes_total`, `bytes_until_t95`, `duplicates` e a curva de cobertura amostrada. Feito depois, com os mecanismos que os geram: a coorte de nós online e `recovery_ms` (item 4); `bytes_control`, `bytes_repair`, `timeouts` e `budget_drops` (item 5). `wall_time_s` é medido em `helper.run_trial`.
3. `policies/fanout.py` e `peer_selection.py`: baselines fixos e comparação inicial. Feito: `FixedFanout`. `peer_selection.py` ficou vazio, porque o sorteio uniforme de `Network.sample_peers` é a única política de seleção usada.
4. `network.py`: perda, latência heterogênea, churn e partição; topologia regular de grau 8. Feito, conforme a "Especificação do modelo": a rede guarda o estado (`online`, `partition_groups`) e aplica a regra de entrega; `simulation.py` agenda o churn e a partição; a cobertura usa a coorte de nós online; `recovery_ms` existe.
5. `protocols.py`: Push-Pull e anti-entropy; `budget.py`: teto de bytes. Feito, conforme a "Especificação do modelo": `Message` com `kind`, `reply` e `ae`; `PushPull`; `Push.on_ae_round` com contagem de timeouts; `Budget` com janelas fixas, consultado em `Network.send`. As execuções de Push sem anti-entropy são idênticas às anteriores.
6. `fanout.py`: heurística adaptativa baseada em estatísticas locais; depois, quiescência como variante de ablação. Feito: `AdaptiveFanout`, com o estado por nó em listas indexadas pelo id; o protocolo informa à política o resultado de cada troca de anti-entropy (`on_ae_result`) e a adoção de versão mais nova (`on_newer_version`).
7. Validação: testes de corretude e comparação com o modelo analítico. Feito para o Push sem falhas: em N=100 e 30 seeds, a cobertura média simulada difere da recorrência da página 3 do PDF em no máximo 0,007 (fanout 1) e 0,006 (fanout 3) nas 12 primeiras rodadas (`tests/test_metrics.py`).
8. `experiments/tuning.py`: tuning com Optuna em N=50 e grade de `quiescence_rounds`; exportar `configs/tuned.yaml`. Feito: 120 trials e 10 pontos de grade, 3.900 simulações.
9. DOE no notebook: piloto, benchmark completo, varredura de escala e análise estatística. Feito: 600 + 17.640 + 540 execuções.
10. Guia de escolha de mecanismos: fatorial de 12 combinações, recomendação por prioridade e validação. Feito: 2.880 + 1.440 execuções (0,8 h e 4,3 h de CPU, somadas de `wall_time_s`).

## Rastreabilidade com a apresentação e plano do DOE

`experiments/doe.py` só gera os planos de execução. Os resultados vêm de `experiments/helper.py` e do notebook.

### Experimentos exigidos pela proposta original

| Parte do PDF | O que deve ser avaliado | Como atender na DES |
|---|---|---|
| Pág. 3 | Push em rede completa sem falhas, `n=100`, fanout 1 e 3; comparar com curva analítica | Validação antes do benchmark, usando rodadas síncronas e seeds |
| Págs. 4–5 | Push; Push-Pull; Push+AE; Adaptativo+AE | Quatro famílias de protocolos sobre o mesmo motor |
| Pág. 5 | `50–500` nós; fanout fixo/adaptativo; perdas; churn; latência; orçamento bytes/nó/intervalo | Variar os fatores, usando as mesmas condições exógenas para todos os protocolos |
| Pág. 5 | Cobertura, T50, T95, tráfego por atualização, duplicação, recuperação e overhead | Emitir métricas por evento e agregar com definições explícitas |
| Pág. 5 | Ajustar parâmetros com Optuna em `N=50`, mesmo número de tentativas por protocolo | Estudo de tuning separado do benchmark final; seeds de treino e de teste distintas |
| Pág. 6 | Estável (0%, 10 ms, 0% churn); perda 1–10%; atraso 10–200 ms; churn 5–20%; partição de dois grupos | Cinco famílias de cenário, com níveis explícitos |
| Págs. 3, 6 | Efeito conjunto de fanout adaptativo e AE sob *churn e perdas*; relatar casos sem ganho | DOE fatorial extra `packet_loss × churn`, comparação pareada com baselines |
| Págs. 6–7 | Escalabilidade, tráfego/nó × N, recuperação após reconexão, seeds e dispersão | Varredura de N de 50 a 500 no DOE principal e de 1.000 a 100.000 em `doe_scale.csv`; tabela e gráficos por N; teste de falhas com reconexão |
| Págs. 7–8 | Nó por processo, Docker/Go/gRPC/netem/OTel (arquitetura antiga) | Mudança de escopo: nó como entidade virtual, transporte de eventos, métricas em CSV. O professor precisa aceitar essa equivalência; ela não mede rede real. |

Os trabalhos relacionados da página 2 (SWIM, HyParView, Plumtree e GossipSub) são contexto. O PDF não exige implementá-los.

### Plano DOE

Na raiz:

```bash
python experiments/doe.py --out experiments/doe
```

Sem `--out`, o script grava os arquivos na pasta `experiments/`.

Saídas:

- `experiments/doe/doe_pilot.csv`: 600 execuções (as cinco variantes com tuning, dois N, 6 cenários incluindo perda+churn, dez seeds).
- `experiments/doe/doe_design.csv`: 588 combinações de fatores do plano completo, ainda sem seeds.
- `experiments/doe/doe_runs.csv`: 17.640 execuções planejadas, cada uma com seed.
- `experiments/doe/doe_scale.csv`: 540 execuções da varredura de escala (N=1.000, 10.000 e 100.000), fora das 17.640.
- `experiments/doe/doe_factorial.csv`: 2.880 execuções do fatorial de mecanismos (12 combinações × 4 cenários × N=100 e 500 × 30 seeds), com `fanout_value` = `common`.
- `experiments/doe/doe_validation.csv`: 1.440 execuções de validação do guia (12 combinações × 4 condições novas × 30 seeds).
- `experiments/doe/doe_summary.txt`: relatório com contagens.

Fase principal: 10 configurações de cenário × 6 variantes × 4 tamanhos de rede × 2 orçamentos × 30 seeds = 14.400 execuções.

- Dez cenários = estável (1), perda de pacotes 1/5/10% (3), latência heterogênea 10–100 e 10–200 ms (2), churn 5/10/20% (3), partição temporária (1).
- Seis variantes = `push_f1`, `push_tuned`, `push_pull`, `push_ae`, `adaptive_ae`, `adaptive_ae_quiescent`. `push_f1` é o baseline fixo sem tuning. As quatro seguintes são as famílias do PDF com os parâmetros de `configs/tuned.yaml`. `adaptive_ae_quiescent` é a ablação da quiescência.
- N = 50, 100, 250, 500; orçamento = 2.048 ou 4.096 bytes/nó a cada 1.000 ms; 30 seeds reservadas ao teste (1000..1029).

Interação perda × churn: perda 1/5/10% × churn 5/10/20% × 6 variantes × N=100/500 × orçamento 4.096 × 30 seeds = 3.240 execuções adicionais. Essa fase testa a hipótese da página 3.

O tuning com Optuna não entra nas 17.640 execuções. Ele ocorre antes do DOE, em N=50, com 30 trials para cada uma das quatro famílias de protocolos e seeds de treino 0..9, distintas das seeds do piloto e do teste. Os parâmetros são congelados em `configs/tuned.yaml` antes da primeira execução do DOE. A função objetivo, a restrição de cobertura e a regra de escolha estão fixadas na seção "Fluxo experimental".

Os níveis 2.048/4.096 bytes, tamanhos 100/250, 30 seeds, duração de 60 s, distribuição uniforme das latências, partição de 0 a 20 s, período de churn de 5 s e grau 8 são decisões deste projeto, não valores do PDF. Os valores de perda, churn e as cinco famílias de cenário são extraídos da apresentação. A seção "Especificação do modelo" define o churn, a partição, a perda e as métricas.

### Varredura de escala

A faixa de 50–500 nós vem da arquitetura original com Docker, gRPC e netem. Na simulação de eventos discretos, um nó é um objeto Python, e a faixa pode crescer. As páginas 6–7 do PDF pedem escalabilidade e tráfego por nó em função de N.

A varredura de escala é um manifesto separado, `experiments/doe/doe_scale.csv`, com 540 execuções: 3 cenários × 6 variantes × 3 tamanhos × 1 orçamento × 10 seeds. O DOE principal continua em N=50–500, porque o PDF define essa faixa e porque repetir as 17.640 execuções em redes maiores multiplicaria o custo sem acrescentar fatores.

| Fator | Níveis da varredura de escala |
|---|---|
| N | 1.000, 10.000, 100.000 |
| Cenários | `stable`, `loss_5pct`, `churn_10pct` |
| Variantes | as seis do DOE principal |
| Orçamento | 4.096 bytes/nó a cada 1.000 ms |
| Seeds | 1000..1009 (as dez primeiras seeds de teste) |
| Topologia, duração | iguais ao DOE principal: regular de grau 8, 60 s |
| Parâmetros | os congelados em `configs/tuned.yaml`, ajustados em N=50 |

Hipóteses que a varredura testa:

- T95 cresce com log N. Em rede completa sem falhas, a teoria do Push prevê cerca de log2(N) + ln(N) rodadas até a cobertura total (Pittel, "On Spreading a Rumor", 1987; citado de memória). Na topologia regular de grau 8, espera-se crescimento também logarítmico, com outra constante.
- `bytes_until_t95 / n_nodes`, o custo por nó de disseminar a atualização, cresce devagar com N.
- A economia de tráfego do fanout adaptativo e da quiescência, medida em N=50–500, continua em N=100.000.
- Os parâmetros ajustados em N=50 continuam adequados em redes 2.000 vezes maiores.

#### Custo medido de uma execução

Medição em uma máquina, Push com fanout 1, rede completa, sem falhas, seed 1, uma execução por linha. "Antes" é o código com o grafo completo do NetworkX e sorteio sobre a lista de vizinhos. "Depois" é o código atual, com rede completa implícita e `Network.sample_peers`.

| N | Horizonte simulado | Mensagens entregues | Antes: tempo, memória de pico | Depois: tempo, memória de pico |
|---|---|---|---|---|
| 100 | 60 s | 11.264 | 0,20 s, 49 MB | 0,15 s, 38 MB |
| 500 | 60 s | 54.882 | 1,55 s, 65 MB | 0,74 s, 38 MB |
| 1.000 | 60 s | 108.917 | 4,87 s, 116 MB | 1,41 s, 39 MB |
| 2.000 | 60 s | 215.913 | 17,96 s, 316 MB | 2,58 s, 41 MB |
| 10.000 | 60 s | 1.056.148 | não medido | 15,64 s, 59 MB |
| 100.000 | 60 s | 10.229.889 | não medido | 250,39 s, 264 MB |
| 100.000 | 15 s | 1.229.890 | não medido | 37,21 s, 264 MB |
| 1.000.000 | 15 s | 8.958.277 | não medido | 313,83 s, 2.320 MB |

Com fanout 3 em N=10.000 e 60 s: 3.364.857 mensagens, 40,40 s, 81 MB.

As medições acima são em rede completa. O DOE e a varredura usam a topologia regular de grau 8. Medição nessa topologia, com as métricas ligadas, Push de fanout 1, 60 s, sem falhas, seed 1, uma execução por linha:

| N | Geração do grafo | Execução | Memória de pico | T95 |
|---|---|---|---|---|
| 1.000 | 0,02 s | 1,71 s | 50 MB | 8.010 ms |
| 10.000 | 0,13 s | 21,84 s | 73 MB | 10.010 ms |
| 100.000 | 2,09 s | 297,97 s | 298 MB | 12.010 ms |

O tempo de execução fica 20% a 40% acima do medido em rede completa, que não tinha as métricas ligadas. T95 aumentou 2.000 ms (4 rodadas) a cada multiplicação de N por 10, o que é compatível com crescimento logarítmico; é uma seed por tamanho, não uma validação.

Causa do custo anterior: o tempo crescia com N², porque cada envio ordenava a lista de N−1 vizinhos e o NumPy copiava essa lista para sortear um peer. No perfil de N=1.000, `Push.on_round` ocupava 5,1 s de 6,4 s. O grafo completo guardava N(N−1)/2 arestas; em N=10.000 seriam 50 milhões de arestas.

O código atual sorteia posições em 0..N−2 e pula o próprio nó. Os sorteios consomem o gerador aleatório do mesmo modo, e as execuções são idênticas às do código anterior: as duplicatas por nó coincidem em quatro configurações comparadas (N=100 e 300, fanout 1, 3 e 5).

O custo atual é proporcional ao número de mensagens, N × fanout × rodadas. Com intervalo de 500 ms e 60 s, são 119 rodadas. A rede completa satura em cerca de 30 rodadas (em N=100.000, 99.999 nós tinham a atualização em t=15 s; em N=1.000.000, 999.885 de 1.000.000). No Push estático, a maior parte das mensagens de uma execução de 60 s é enviada depois da saturação.

Custo por protocolo, medido em N=10.000 na topologia regular, fanout 1, 60 s, sem falhas, seed 1, uma execução por linha, com o orçamento de 4.096 bytes ligado:

| Protocolo | Execução | Memória de pico | T95 | `bytes_control / bytes_total` |
|---|---|---|---|---|
| Push | 20,75 s | 75 MB | 10.010 ms | 0% |
| Push-Pull | 24,44 s | 74 MB | 5.020 ms | 0,5% |
| Push + anti-entropy a cada 1.000 ms | 48,00 s | 99 MB | 6.020 ms | 5,9% |

A anti-entropy a cada 1.000 ms mais que dobra o tempo de execução, porque cada troca acrescenta duas mensagens por nó a cada segundo às duas `DATA` do Push.

Três mudanças posteriores reduziram o tempo sem alterar nenhum resultado:

- A entrega de cada mensagem é um callback do `Timeout` do SimPy, em vez de um processo por mensagem. A fila de eventos recebe um evento por mensagem em vez de três.
- Há um processo SimPy por intervalo (rodada de gossip, tick de anti-entropy), que percorre os nós em ordem de id, em vez de um processo por nó.
- O sorteio de um único peer usa `rng.integers` em vez de `rng.choice(..., size=1, replace=False)`. As duas chamadas devolvem o mesmo valor e deixam o gerador no mesmo estado (conferido em 14 tamanhos de população, 50.000 sorteios cada). Com latência constante, o sorteio da latência é dispensado.

As mesmas medições com o código atual, uma execução por linha, máquina sem outra carga:

| Caso | Antes | Depois |
|---|---|---|
| N=10.000, Push | 20,75 s | 6,33 s |
| N=10.000, Push-Pull | 24,44 s | 7,45 s |
| N=10.000, Push + anti-entropy a cada 1.000 ms | 48,00 s | 14,09 s |
| N=100.000, Push | 297,97 s, 298 MB | 80,73 s, 193 MB |

T95 e `bytes_total` dessas execuções são iguais antes e depois. As 600 execuções do piloto e as 17.640 do DOE foram executadas com o código anterior e com o atual: todas as colunas do `summary_df`, exceto `wall_time_s`, e todas as curvas de cobertura são idênticas.

Custo medido dos experimentos, em um notebook com 24 núcleos (32 threads). `wall_time_s` inclui a disputa por CPU entre os processos:

| Etapa | Execuções | Tempo de relógio | Soma de `wall_time_s` |
|---|---|---|---|
| Tuning | 3.900 | 2 min | não medido |
| Piloto | 600 | 22 s | 0,2 h |
| DOE | 17.640 | 9 min | 4,9 h |
| Varredura de escala | 540 | cerca de 75 min, com 22 a 24 processos | 23,6 h |

Na varredura, a mediana de `wall_time_s` por execução em N=100.000 vai de 98 s (`adaptive_ae_quiescent`) a 729 s (`push_ae`). Cada processo ocupa cerca de 300 MB em N=100.000.

#### Itens propostos e não adotados

- N=10.000 como escala principal do DOE. O DOE principal fica em 50–500. A varredura cobre as escalas maiores com 540 execuções.
- Motor próprio com `heapq`, Rust ou estado em arrays NumPy. O SimPy executa N=100.000 com menos de 300 MB. Trocar o motor só faz sentido se N=1.000.000 com 60 s entrar no plano.
- Pico de memória e eventos por segundo como métricas. A pergunta de pesquisa é sobre os protocolos. O `summary_df` registra só `wall_time_s`.
- N=1.000.000 no manifesto. Uma execução de Push com fanout 1 e 15 s simulados já foi medida (tabela acima). Com 60 s, seriam cerca de 119 milhões de mensagens por execução.

#### Decisões da varredura de escala

A varredura foi executada como está no manifesto. Três opções ficaram de fora:

- N=1.000.000 como caso único de estresse, com horizonte menor que 60 s. Horizontes diferentes tornam `bytes_total` não comparável entre escalas; `bytes_until_t95` continua comparável.
- Rede completa. O manifesto usa a topologia regular de grau 8, como o DOE principal. A rede completa permitiria comparar com a previsão teórica.
- Partição temporária. A varredura usa só os cenários estável, perda de 5% e churn de 10%.

### Checklist de implementação

Estado: os 13 itens estão atendidos, com três simplificações em relação ao texto abaixo. Há uma única atualização por execução (versão 0 para 1), então não há conjunto de IDs vistos. A visão de peers é estática e fica em `Network`, não em `Node`. As métricas são contadores agregados, sem registro por evento.

1. Modelo de eventos: `Simulation` com SimPy; relógio e ordem determinística de eventos simultâneos.
2. Estado local: `Node` com ID, peers, versões, IDs vistos, contadores de duplicatas, timeouts e bytes. As políticas não leem estado global.
3. Mensagens versionadas: criação de atualização por ID e versão, entrega, deduplicação e atualização da versão local.
4. Membership e peers: política de visão local e transições join/leave; definir o que acontece com a memória do nó na reconexão.
5. Transporte: latência, perda e partição, com regras explícitas para mensagens em trânsito e para endpoints que mudam de estado.
6. Protocolos: Push, Push-Pull, anti-entropy periódica e Push adaptativo + AE; frequência e tamanho real das mensagens configuráveis.
7. Políticas: seleção de peers, fanout fixo ou adaptativo só por estatísticas locais, limites de fanout, orçamento de dados, controle e reparo cobrado no envio.
8. Métricas: cobertura sobre a coorte elegível, T50/T95 (inclusive quando não atingidos), bytes de dados, controle e reparo, duplicações, overhead, tráfego por nó e tempo de recuperação após a volta da conectividade.
9. Validação analítica: reproduzir o modelo Push sem falhas da pág. 3 com N=100 e fanout 1 e 3; testes para perda=100%, partição, deduplicação, orçamento e reprodutibilidade.
10. Helper do notebook: `run_trial`, `run_manifest` e `summarize_results` consomem as linhas de `doe_*.csv`, registram status e salvam dados brutos sem depender da ordem das execuções.
11. Tuning: função objetivo em `experiments/tuning.py`; Optuna em N=50 com o mesmo número de trials por família e seeds de treino separadas do piloto e do teste final; exportar `configs/tuned.yaml`.
12. Análise: piloto → estudo principal → interação; comparação pareada por cenário e seed, dispersão, cobertura × T95 × tráfego, recuperação e casos em que o adaptativo perde.
13. Relatório: versões, seeds, configurações, hipóteses, casos não convergentes, e o limite de que uma DES não valida custos reais de rede, sockets ou containers.

### Como usar o DOE no notebook

O notebook carrega o manifesto pronto, em vez de repetir a lista de cenários em células:

```python
from pathlib import Path
import pandas as pd

ROOT = Path.cwd().resolve()
if ROOT.name == "experiments":
    ROOT = ROOT.parent

plan = pd.read_csv(ROOT / "experiments" / "doe" / "doe_pilot.csv")
print(plan.groupby(["phase", "scenario"]).size())

from helper import RESULTS, run_manifest
tuned = yaml.safe_load((ROOT / "configs" / "tuned.yaml").read_text())
summary_df, coverage_df = run_manifest(plan, tuned, RESULTS / "doe_pilot")
```

Não execute a matriz completa antes da validação e do tuning. Primeiro rodar o caso analítico sem falhas, depois o tuning em N=50, depois o piloto de 600 execuções com os parâmetros congelados. Inspecionar as métricas do piloto antes de avançar às 17.640 execuções. A varredura de escala (540 execuções) roda por último.
