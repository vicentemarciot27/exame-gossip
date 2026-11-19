# Gossip Simulator

Simulador de **eventos discretos** para comparar estratégias de disseminação Gossip em uma rede simulada: **Push**, **Push-Pull**, **Push + anti-entropy** e **Push com fanout adaptativo + anti-entropy**.

A pesquisa compara **cobertura**, **T50/T95**, **tráfego em bytes**, **duplicação**, **overhead de controle** e **recuperação após falhas**, sob latência heterogênea, perda de pacotes, churn e partições. O objetivo é testar *comportamento algorítmico*, não medir desempenho real de gRPC, containers ou sockets. O DOE principal usa 50–500 nós simulados. Uma varredura de escala separada usa 1.000, 10.000 e 100.000 nós.

## Estrutura do projeto

```text
.
├── pyproject.toml
├── README.md
├── configs/
│   ├── baseline.yaml
│   └── tuned.yaml          # exportado pelo tuning; ainda não existe
├── experiments/
│   ├── helper.py
│   ├── tuning.py           # a criar
│   ├── doe.py
│   ├── doe/                # manifestos CSV gerados por doe.py
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
| `src/network.py` | Guarda a topologia, sorteia peers (`sample_peers`) sem montar a lista de vizinhos, transporta mensagens **somente pelo relógio simulado**, aplica latência, perda, churn e partições. Único lugar autorizado a entregar mensagens. |
| `src/protocols.py` | Implementa Push, Push-Pull e anti-entropy: decide quais mensagens enviar e quando reconciliar versões. Não manipula a fila de eventos diretamente. |
| `src/metrics.py` | Registra eventos e calcula curvas de cobertura, T50, T95, bytes, controle, duplicatas e tempo de recuperação. Não interfere nas decisões dos nós. |
| `src/policies/fanout.py` | Fanout fixo e adaptativo. A política adaptativa usa apenas estatísticas **locais** observáveis pelo nó. |
| `src/policies/budget.py` | Aplica orçamento de comunicação por nó e janela de tempo. Inclui mensagens de dados, controle e reparos. |
| `src/policies/peer_selection.py` | Escolha de destinatários; opera sobre a visão local de peers. O sorteio uniforme sem reposição já existe em `Network.sample_peers`; este arquivo só é criado se houver uma política não uniforme. |
| `configs/*.yaml` | Cenários declarativos: duração, nós, topologia, latência, perda, churn, orçamento e parâmetros do protocolo. |
| `configs/tuned.yaml` | Hiperparâmetros congelados de cada família de protocolo, exportados pelo tuning. Ainda não existe. |
| `experiments/helper.py` | Cola entre simulador e notebook: `run_trial()`, `run_manifest()` e `summarize_results()`. Lê configurações, executa simulações e devolve `pandas.DataFrame`s. **Sem lógica de Gossip aqui**. |
| `experiments/tuning.py` | Função objetivo do Optuna e espaço de busca de cada família de protocolo. A criar. |
| `experiments/doe.py` | Gera os manifestos CSV do DOE. Não executa simulações. |
| `experiments/notebook.ipynb` | Orquestra validação, estudos Optuna, execução do DOE, gráficos e análise. Não contém a implementação da simulação. |
| `pyproject.toml` | Define o pacote, as dependências e os extras para notebooks e testes. |

## Bibliotecas e por que usar cada uma

O projeto separa bibliotecas necessárias **para simular** das bibliotecas usadas **para experimentar e analisar**.

### Dependências principais

| Biblioteca | Uso |
|---|---|
| [SimPy](https://simpy.readthedocs.io/) | **Motor de eventos discretos**. Oferece relógio virtual (`env.now`), processos (`env.process`) e agendamento (`yield env.timeout`). Nada precisa esperar em tempo real. |
| [NumPy](https://numpy.org/doc/) | Geradores pseudoaleatórios e seeds para peer selection, perdas e latências; permite separar fluxos de aleatoriedade por componente. |
| [NetworkX](https://networkx.org/documentation/stable/) | Gera a topologia regular de grau 8 do DOE (a implementar). A rede completa é implícita e não usa NetworkX. Não simula a transmissão. |
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
| [Optuna](https://optuna.readthedocs.io/) | Ajuste de hiperparâmetros em N=50, depois da validação e antes do benchmark final. Usa seeds de treino distintas das seeds do DOE. |

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

Testes: `uv run pytest -q`.

**Observação:** a implementação está parcial. A seção "Implementação (timeline)" lista o que existe em `src/` e o que falta. O notebook é um **roteiro de experimento**, não uma simulação pronta para executar. O arquivo `configs/baseline.yaml` incluído é uma proposta inicial de configuração.

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

### Papel do DOE e do Optuna

O DOE e o Optuna são etapas complementares. A tabela compara o objetivo, os fatores variados, o resultado e o momento de cada uma.

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

- `gossip_interval_ms` corresponde a `simulation.gossip_interval_ms` em `configs/baseline.yaml`. No Adaptativo + AE ele fica fixo em 500 ms. Os demais hiperparâmetros ainda não têm chave de configuração.
- `duplicate_threshold`: fração de `DATA` duplicadas, entre as `DATA` recebidas pelo nó desde a rodada anterior, acima da qual o nó reduz o fanout em 1.
- `timeout_threshold`: fração de trocas de anti-entropy com timeout acima da qual o nó aumenta o fanout em 1. A janela de trocas consideradas é definida na implementação do fanout adaptativo (item 6 da timeline).

O orçamento de bytes por nó e janela é uma restrição experimental. O Optuna não o ajusta, porque aumentar o orçamento melhoraria o desempenho sem medir a qualidade do algoritmo.

### Quiescência após saturação local

No plano original do PDF, não há mecanismo para fazer os nós pararem de enviar mensagens. No Push, um nó que possui a atualização envia em todas as rodadas até `duration_ms`. Em `adaptive_ae`, o fanout varia entre 1 e 5, então o mínimo ainda é uma mensagem por rodada. O orçamento limita os bytes por janela, mas não suspende a disseminação.

A extensão suspende o Push de uma atualização quando o nó observa saturação local, e mantém a anti-entropy periódica.

Cada nó tem dois estados por atualização, ativo e quiescente, e um contador `saturation_count`. Um nó sem a atualização não envia `DATA` e não participa dessa máquina de estados.

| Item | Definição |
|---|---|
| Mecanismo | No estado quiescente, a política de fanout devolve 0. A anti-entropy continua nos dois estados. Fica em `src/policies/fanout.py`; não há módulo novo. |
| Evidência de saturação | Desde a rodada anterior, o nó recebeu pelo menos uma `DATA` duplicada, ou concluiu uma troca de anti-entropy em que o peer tinha a mesma versão. As duas são estatísticas locais e não exigem mensagens extras. |
| Contagem | A cada rodada de gossip com evidência, `saturation_count` aumenta 1. Uma rodada sem evidência não zera o contador. |
| Entrada na quiescência | `saturation_count` atinge `quiescence_rounds`. |
| Retomada do Push | O nó recebe uma versão mais nova, ou uma troca de anti-entropy mostra um peer com versão mais antiga. O contador volta a 0 e o nó volta ao estado ativo. |
| Timeouts | Não contam como evidência e não zeram o contador. Um peer sem resposta pode estar offline ou do outro lado de uma partição. |
| Churn | Um nó que fica offline mantém o estado e o contador. |
| Dependência | Só é usada em variantes com anti-entropy. Push com parada deixa uma fração de nós sem a atualização (Demers et al., "Epidemic Algorithms for Replicated Database Maintenance", 1987); a anti-entropy recupera esses nós. |
| Tuning | `quiescence_rounds`, em grade de 1 a 10, com os parâmetros de `adaptive_ae` congelados. |

A quiescência é uma heurística. As duas evidências indicam que a atualização é comum na vizinhança do nó, mas não provam que todos os peers a têm. O DOE mede o erro dessa heurística pela cobertura, pelo T95 e pelo `recovery_ms` de `adaptive_ae_quiescent` contra `adaptive_ae`.

A evidência por anti-entropy é necessária. Só com duplicatas de Push, os últimos nós ativos deixariam de receber duplicatas, porque os peers já quiescentes não enviam `DATA`, e nunca entrariam em quiescência. Pelo mesmo motivo, uma rodada sem evidência não zera o contador.

A quiescência entra no DOE como ablação do fanout adaptativo, com uma única variante, `adaptive_ae_quiescent`. Ela difere de `adaptive_ae` somente pela quiescência.

O tráfego total das variantes sem quiescência cresce com `duration_ms`, porque elas enviam até o fim. Por isso as métricas reportam também os bytes enviados até T95, além do total.

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

Regras de mensagens, falhas, orçamento e métricas. `src/` implementa hoje só a latência e o Push; cada regra restante entra no item correspondente da timeline. Os diagramas de estados (churn, caminho de uma mensagem e quiescência) estão em <https://claude.ai/artifact/XyksbJC62AGpVtbRr3LHFe>, página privada do autor do projeto.

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

## Contrato simples entre notebook e simulador

Sugestão de interface pública em `experiments/helper.py`:

```python
def run_trial(config: dict, seed: int) -> tuple[dict, pd.DataFrame]:
    """Executa uma simulação.

    Retorna a linha de resumo e a curva de cobertura dessa execução.
    """

def run_manifest(plan: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Executa cada linha de um manifesto do DOE.

    Retorna (summary_df, coverage_df).
    """

def summarize_results(summary_df: pd.DataFrame) -> pd.DataFrame:
    """Agrega por cenário e variante: medianas, dispersão e fração de
    execuções que atingiram T95."""
```

`run_manifest` e a função objetivo de `experiments/tuning.py` chamam `run_trial`. Assim, o tuning e o DOE executam o mesmo código de simulação.

Cada variante muda **somente** a escolha de protocolo/políticas; a infraestrutura simulada deve ser a mesma. O helper pode começar sequencial e ser paralelizado depois.

**`summary_df`: uma linha por execução**, colunas sugeridas:

```text
run_id, scenario, protocol_variant, seed, n_nodes, coverage_final,
t50_ms, t95_ms, bytes_total, bytes_until_t95, bytes_control, bytes_repair,
duplicates, timeouts, budget_drops, recovery_ms, wall_time_s
```

`wall_time_s` é o tempo real da execução, em segundos. Mede o custo do simulador, não do protocolo, e é usado na varredura de escala.

**`coverage_df`: múltiplas linhas por execução**, colunas:

```text
run_id, scenario, protocol_variant, seed, time_ms, coverage
```

`run_id` e `protocol_variant` vêm do manifesto do DOE. A coluna `protocol` do manifesto não distingue os tratamentos: ela vale `push` em `push_f1`, `push_tuned`, `push_ae`, `adaptive_ae` e `adaptive_ae_quiescent`. Os demais fatores do manifesto, como o orçamento, são obtidos por junção em `run_id`.

`coverage` é uma fração entre 0 e 1 sobre a coorte elegível. `t95_ms` é `NaN` se a execução não atingir 95% até o horizonte da simulação; essas execuções não são excluídas. A seção "Especificação do modelo" define cada coluna.

## Organização do `experiments/notebook.ipynb`

O notebook acompanha o fluxo de uma pesquisa, de cima para baixo:

1. **Imports e configuração:** hipóteses em Markdown, `yaml.safe_load` de `configs/baseline.yaml`, seeds de treino e número de trials.
2. **Validação do simulador:** rede completa sem falhas, N=100, fanout 1 e 3; comparar a curva Push com o modelo analítico.
3. **Tuning com Optuna em N=50:** um estudo por família de protocolo, com o mesmo número de trials e a função objetivo de `experiments/tuning.py`.
4. **Exportação dos parâmetros otimizados:** gravar a configuração escolhida de cada família em `configs/tuned.yaml`.
5. **Carregamento do DOE:** ler os manifestos de `experiments/doe/`, incluindo `doe_scale.csv`.
6. **Execução do piloto e do benchmark completo:** `run_manifest` sobre `doe_pilot.csv`, depois sobre `doe_runs.csv` e por último sobre `doe_scale.csv`; conferir total de execuções, valores ausentes e execuções sem T95.
7. **Análise estatística e visualizações:** cobertura × tempo, T95 × tráfego, T95 e bytes por nó × N de 50 a 100.000, medianas e intervalos, casos em que o adaptativo perde, conclusões e limitações.

O notebook define os estudos Optuna e os gráficos. A simulação fica em `src/` e é chamada por `experiments/helper.py`.

No estado atual, só executam as células de imports, a curva analítica da validação e o carregamento do DOE. As demais estão comentadas até `experiments/helper.py`, `experiments/tuning.py` e o restante de `src/` serem implementados.

### Exemplos de células (API a implementar)

Estudo Optuna por família, com `objective` e `constraints` a implementar em `experiments/tuning.py`:

```python
import optuna
from tuning import objective, constraints

N_TRIALS = 30  # igual para as quatro famílias
TUNING_SEEDS = list(range(10))  # disjuntas do piloto e do DOE
tuning_config = deepcopy(BASE_CONFIG)  # configs/baseline.yaml
tuning_config["network"]["nodes"] = 50

studies = {}
# Quatro famílias do PDF. `objective` roda os três cenários de tuning.
# A grade de quiescence_rounds vem depois, com adaptive_ae congelado.
for family in ("push", "push_pull", "push_ae", "adaptive_ae"):
    study = optuna.create_study(
        directions=["minimize", "minimize"],  # T95 e bytes
        # TPE em vez do NSGA-II padrão: com população 50, o NSGA-II
        # faria apenas amostragem aleatória em 30 trials.
        sampler=optuna.samplers.TPESampler(seed=0, constraints_func=constraints),
    )
    study.optimize(
        lambda trial: objective(trial, family, tuning_config, TUNING_SEEDS),
        n_trials=N_TRIALS,
    )
    studies[family] = study
```

Curva de cobertura a partir do `coverage_df` devolvido por `run_manifest`:

```python
import seaborn as sns
import matplotlib.pyplot as plt

sns.lineplot(
    data=coverage_df,
    x="time_ms",
    y="coverage",
    hue="protocol_variant",
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
- **Optuna:** ajustar em N=50 com seeds de treino disjuntas das seeds do piloto e do DOE, mesmo número de trials por família e orçamento fixo. Não reajustar os parâmetros depois de observar os resultados do DOE.
- **Logs/CSV:** salvar resultados brutos, configuração, seed e versão do código. Evitar commit de arquivos de saída grandes.

## Implementação (timeline)

Estado em 18/11/2026: os itens 1 e 2 estão implementados e testados (`tests/test_network.py`, `tests/test_push.py`, `tests/test_metrics.py`). A parte do item 7 que não depende de falhas também está feita. Os demais estão pendentes.

1. `simulation.py` + `network.py` + `protocols.py`: Push simples, sem falhas, um evento versionado. Feito: rede completa implícita, latência uniforme em ms inteiros, fanout fixo, sorteio uniforme de peers sem reposição, um gerador aleatório por componente (rede, protocolo, injeção).
2. `metrics.py`: as colunas definidas em "Especificação do modelo", com contadores agregados. Um registro por mensagem não cabe na memória em N=100.000 (10 milhões de mensagens por execução). Feito: `coverage_final`, `t50_ms`, `t95_ms`, `bytes_total`, `bytes_until_t95`, `duplicates` e a curva de cobertura amostrada. Pendente: `bytes_control`, `bytes_repair`, `timeouts`, `budget_drops` e `recovery_ms` entram com os mecanismos que os geram; `wall_time_s` entra em `experiments/helper.py`; a coorte de nós online entra com o churn.
3. `policies/fanout.py` e `peer_selection.py`: baselines fixos e comparação inicial.
4. `network.py`: perda, latência heterogênea, churn e partição; topologia regular de grau 8.
5. `protocols.py`: Push-Pull e anti-entropy; `budget.py`: teto de bytes.
6. `fanout.py`: heurística adaptativa baseada em estatísticas locais; depois, quiescência como variante de ablação.
7. Validação: testes de corretude e comparação com o modelo analítico. Feito para o Push sem falhas: em N=100 e 30 seeds, a cobertura média simulada difere da recorrência da página 3 do PDF em no máximo 0,007 (fanout 1) e 0,006 (fanout 3) nas 12 primeiras rodadas (`tests/test_metrics.py`).
8. `experiments/tuning.py`: tuning com Optuna em N=50 e grade de `quiescence_rounds`; exportar `configs/tuned.yaml`.
9. DOE no notebook: piloto, benchmark completo, varredura de escala e análise estatística.

## Rastreabilidade com a apresentação (8 slides) e DOE completo

**Status:** a implementação está parcial. Existem o transporte, o Push sem falhas em rede completa e as métricas de cobertura, T50/T95, bytes e duplicatas, com testes. Falhas de rede, Push-Pull, anti-entropy, políticas, `experiments/helper.py` e `experiments/tuning.py` não existem. O notebook contém exemplos comentados; `experiments/doe.py` **gera somente planos de execução**, não resultados científicos.

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
| Págs. 6–7 | Escalabilidade, tráfego/nó × N, recuperação após reconexão, seeds e dispersão | Varredura de N de 50 a 500 no DOE principal e de 1.000 a 100.000 em `doe_scale.csv`; tabela e gráficos por N; teste de falhas com reconexão |
| Págs. 7–8 | Nó por processo, Docker/Go/gRPC/netem/OTel (arquitetura antiga) | **Mudança de escopo:** nó como entidade virtual, transporte de eventos, métricas em CSV. Esta equivalência precisa ser aceita pelo professor; não mede rede real. |

Os trabalhos relacionados da **página 2** (SWIM, HyParView, Plumtree e GossipSub) contextualizam a pesquisa; o PDF **não exige implementar** cada um deles.

### Plano DOE

Execute na raiz:

```bash
python experiments/doe.py --out experiments/doe
```

Sem `--out`, o script grava os arquivos na pasta `experiments/`.

Saídas:

- `experiments/doe/doe_pilot.csv`: **600 execuções** (as cinco variantes com tuning, dois N, 6 cenários incluindo perda+churn, dez seeds).
- `experiments/doe/doe_design.csv`: **588 combinações** de fatores do plano completo, ainda sem seeds.
- `experiments/doe/doe_runs.csv`: **17.640 execuções planejadas**, cada uma com seed.
- `experiments/doe/doe_scale.csv`: **540 execuções** da varredura de escala (N=1.000, 10.000 e 100.000), fora das 17.640.
- `experiments/doe/doe_summary.txt`: relatório com contagens.

**Fase principal:** 10 configurações de cenário × 6 variantes × 4 tamanhos de rede × 2 orçamentos × 30 seeds = **14.400** execuções.

- Dez cenários = estável (1), perda de pacotes 1/5/10% (3), latência heterogênea 10–100 e 10–200 ms (2), churn 5/10/20% (3), partição temporária (1).
- Seis variantes = `push_f1`, `push_tuned`, `push_pull`, `push_ae`, `adaptive_ae`, `adaptive_ae_quiescent`. `push_f1` é o baseline fixo sem tuning. As quatro seguintes são as famílias do PDF com os parâmetros de `configs/tuned.yaml`. `adaptive_ae_quiescent` é a ablação da quiescência.
- N = 50, 100, 250, 500; orçamento = 2.048 ou 4.096 bytes/nó a cada 1.000 ms; 30 seeds reservadas ao teste (1000..1029).

**Interação crítica:** perda 1/5/10% × churn 5/10/20% × 6 variantes × N=100/500 × orçamento 4.096 × 30 seeds = **3.240** execuções adicionais. Assim, a hipótese da página 3 é testada diretamente.

**O tuning com Optuna não está incluído nessas 17.640 execuções.** Ele ocorre antes do DOE, em N=50, com 30 trials para cada uma das quatro famílias de protocolos e seeds de treino 0..9, distintas das seeds do piloto e do teste. Os parâmetros são congelados em `configs/tuned.yaml` antes da primeira execução do DOE. A função objetivo, a restrição de cobertura e a regra de escolha estão fixadas na seção "Fluxo experimental".

**Importante: os níveis 2.048/4.096 bytes, tamanhos 100/250, 30 seeds, duração de 60 s, distribuição uniforme das latências, partição de 0 a 20 s, período de churn de 5 s e grau 8 são decisões deste projeto para o DOE**, não valores determinados pelo PDF. Os valores de perda, churn e as cinco famílias de cenário são extraídos da apresentação. A seção "Especificação do modelo" define o churn, a partição, a perda e as métricas.

### Varredura de escala

A faixa de 50–500 nós vem da arquitetura original com Docker, gRPC e netem. Na simulação de eventos discretos, um nó é um objeto Python, e a faixa pode crescer. As páginas 6–7 do PDF pedem escalabilidade e tráfego por nó em função de N.

A varredura de escala é um manifesto separado, `experiments/doe/doe_scale.csv`, com **540 execuções**: 3 cenários × 6 variantes × 3 tamanhos × 1 orçamento × 10 seeds. O DOE principal continua em N=50–500, porque o PDF define essa faixa e porque repetir as 17.640 execuções em redes maiores multiplicaria o custo sem acrescentar fatores.

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

Essas medições são em rede completa. O DOE e a varredura usam a topologia regular de grau 8, que ainda não existe em `src/`; o tempo e a memória nessa topologia precisam ser medidos em N=1.000, 10.000 e 100.000 antes de rodar a varredura.

Causa do custo anterior: o tempo crescia com N², porque cada envio ordenava a lista de N−1 vizinhos e o NumPy copiava essa lista para sortear um peer. No perfil de N=1.000, `Push.on_round` ocupava 5,1 s de 6,4 s. O grafo completo guardava N(N−1)/2 arestas; em N=10.000 seriam 50 milhões de arestas.

O código atual sorteia posições em 0..N−2 e pula o próprio nó. Os sorteios consomem o gerador aleatório do mesmo modo, e as execuções são idênticas às do código anterior: as duplicatas por nó coincidem em quatro configurações comparadas (N=100 e 300, fanout 1, 3 e 5).

O custo atual é proporcional ao número de mensagens, N × fanout × rodadas. Com intervalo de 500 ms e 60 s, são 119 rodadas. A rede completa satura em cerca de 30 rodadas (em N=100.000, 99.999 nós tinham a atualização em t=15 s; em N=1.000.000, 999.885 de 1.000.000). No Push estático, a maior parte das mensagens de uma execução de 60 s é enviada depois da saturação.

Estimativa para as 540 execuções: 25 a 35 horas de CPU, quase todas em N=100.000. A estimativa supõe que as seis variantes somam cerca de doze vezes o custo de `push_f1`; só o Push com fanout 1 e 3 foi medido, em rede completa e sem falhas. As execuções são independentes e podem rodar em paralelo, uma por processo.

#### Itens propostos e não adotados

- **N=10.000 como escala principal do DOE.** O DOE principal fica em 50–500. A varredura cobre as escalas maiores com 540 execuções.
- **Motor próprio com `heapq`, Rust, estado em arrays NumPy.** O SimPy executa N=100.000 em memória abaixo de 300 MB. Só há motivo para trocar o motor se N=1.000.000 com 60 s entrar no plano.
- **Callback no `Timeout` em vez de um processo por mensagem.** Medido em um protótipo, N=10.000: 8,9 s contra 11,3 s (22% menos). O ganho não justifica mudar o transporte agora.
- **Pico de memória e eventos por segundo como métricas.** A pergunta de pesquisa é sobre os protocolos. O `summary_df` registra só `wall_time_s`.
- **N=1.000.000 no manifesto.** Uma execução de Push com fanout 1 e 15 s simulados já foi medida (tabela acima). Com 60 s, seriam cerca de 119 milhões de mensagens por execução.

#### Decisões em aberto da varredura de escala

- Incluir N=1.000.000 como caso único de estresse, com horizonte menor que 60 s. Horizontes diferentes tornam `bytes_total` não comparável entre escalas; `bytes_until_t95` continua comparável.
- Topologia. O manifesto usa a regular de grau 8, como o DOE principal. A rede completa permitiria comparar com a previsão teórica.
- Conjunto de cenários. A partição temporária ficou fora da varredura.

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
10. **Helper do notebook:** implementar `run_trial`, `run_manifest` e `summarize_results` para consumir as linhas `doe_*.csv`, registrar status e salvar dados brutos sem depender da ordem das execuções.
11. **Tuning:** implementar a função objetivo em `experiments/tuning.py`; rodar Optuna em N=50 com o mesmo número de trials por família e seeds de treino separadas do piloto e do teste final; exportar `configs/tuned.yaml`.
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

plan = pd.read_csv(ROOT / "experiments" / "doe" / "doe_pilot.csv")
print(plan.groupby(["phase", "scenario"]).size())

# A implementar em experiments/helper.py:
# from helper import run_manifest
# summary_df, coverage_df = run_manifest(plan)
```

**Não executar a matriz completa antes da validação e do tuning.** Primeiro rodar o caso analítico sem falhas, depois o tuning em N=50, depois o piloto de 600 execuções com os parâmetros congelados. Inspecionar os logs e as métricas do piloto antes de avançar às 17.640 execuções. A varredura de escala (540 execuções) roda por último. O volume total é uma proposta de cobertura experimental, não uma obrigação do PDF nem uma garantia de runtime aceitável.
