"""Único lugar que entrega mensagens. Protocolos chamam `Network.send`; a rede
decide quando a mensagem chega.
"""

from __future__ import annotations

from functools import partial

import networkx as nx
import numpy as np


def random_regular_neighbors(n, degree, rng):
    """Matriz (n, degree) de vizinhos de um grafo regular aleatório conexo."""
    while True:
        graph = nx.random_regular_graph(degree, n, seed=int(rng.integers(2**32)))
        if nx.is_connected(graph):  # com grau 8 quase sempre sai na primeira
            return np.array([sorted(graph[i]) for i in range(n)])


class Network:
    def __init__(
        self,
        env,
        n,
        rng,
        metrics,
        latency_ms=(10, 10),
        neighbors=None,
        packet_loss=0.0,
        loss_rng=None,
        budget=None,
    ):
        self.env = env
        self.n = n
        self.rng = rng  # só latência
        self.metrics = metrics
        self.latency_ms = latency_ms  # (mín, máx) em ms inteiros
        # None = rede completa implícita, sem lista de arestas na memória.
        # senão, matriz (n, grau) de vizinhos
        self.neighbors = neighbors
        self.packet_loss = packet_loss  # probabilidade por mensagem
        self.loss_rng = loss_rng  # só perda, separado da latência
        self.budget = budget  # None = sem teto de bytes
        # estado de falhas, mexido pela simulação
        self.online = [True] * n  # nó offline não recebe
        self.partition_groups = 0  # 0 = sem partição; 2 = dois grupos isolados
        self.handlers = {}  # id do nó -> handler(src, message)

    def register(self, node_id, handler):
        self.handlers[node_id] = handler

    def sample_peers(self, node_id, k, rng):
        """Até `k` vizinhos distintos de `node_id`, sorteados com o `rng` de quem chama.

        Custo O(k), não O(n): a lista de vizinhos da rede completa nunca é montada.
        """
        if k == 0:
            return []  # nó quiescente; rng.choice com size=0 também não consome o gerador
        if self.neighbors is not None:
            peers = self.neighbors[node_id]
            if k == 1:
                # mesmo sorteio e mesmo estado do gerador que rng.choice com
                # size=1, por um caminho 4x mais rápido do NumPy
                return [int(peers[rng.integers(0, len(peers))])]
            return rng.choice(peers, size=min(k, len(peers)), replace=False).tolist()
        # rede completa: sorteia em 0..n-2 e soma 1 a partir de node_id,
        # o que pula o próprio nó
        if k == 1:
            pick = int(rng.integers(0, self.n - 1))
            return [pick + (pick >= node_id)]
        picks = rng.choice(self.n - 1, size=min(k, self.n - 1), replace=False)
        return (picks + (picks >= node_id)).tolist()

    def send(self, src, dst, message):
        """Agenda a entrega de `message` de `src` para `dst`.

        False só se o orçamento de `src` barrou o envio. Mensagem perdida
        devolve True: o remetente não fica sabendo da perda.
        """
        # tolist(): `in` sobre lista é 10x mais rápido que sobre array do NumPy
        assert src != dst and (
            self.neighbors is None or dst in self.neighbors[src].tolist()
        ), f"{src} e {dst} não são vizinhos"
        # sem saldo: descarta, não enfileira
        if self.budget and not self.budget.try_spend(src, message.size_bytes):
            self.metrics.on_budget_drop()
            return False
        # bytes contam no envio, mesmo se a mensagem se perder depois
        self.metrics.on_send(message.size_bytes, message.kind, message.reply)
        if self.packet_loss and self.loss_rng.random() < self.packet_loss:
            return True
        low, high = self.latency_ms
        # latência constante dispensa o sorteio; este gerador só serve à latência
        delay = low if low == high else int(self.rng.integers(low, high + 1))
        # callback no Timeout em vez de um processo SimPy por mensagem:
        # um evento na fila em vez de três
        arrival = self.env.timeout(delay)
        arrival.callbacks.append(partial(self._deliver, src, dst, message))
        return True

    def _deliver(self, src, dst, message, _event):
        # churn e partição valem no instante da entrega, não do envio
        if self._reachable(src, dst):
            self.handlers[dst](src, message)

    def _reachable(self, src, dst):
        groups = self.partition_groups
        same_group = not groups or src % groups == dst % groups
        return self.online[dst] and same_group
