"""Contadores de uma execução. As métricas observam a simulação e não
interferem nas decisões dos nós.

As definições de cada métrica estão no README, seção "Especificação do modelo".
"""

from __future__ import annotations

from collections import Counter


class Metrics:
    def __init__(self, env, n_nodes):
        self.env = env  # simpy.Environment: só para ler o instante atual
        # Coorte elegível: nós que contam no denominador da cobertura.
        # ponytail: sem churn, a coorte são todos os nós; quando o churn
        # existir, ela passa a ser o número de nós online no instante.
        self.cohort = n_nodes
        self.informed = 0  # nós da coorte que já têm a atualização
        self.coverage_events = [(0, 0.0)]  # (instante, cobertura) a cada mudança
        self.crossing_ms = {50: None, 95: None}  # T50 e T95; None = ainda não ocorreu
        self.bytes_by_time = Counter()  # instante do envio -> bytes enviados nele
        self.duplicates = 0

    def on_send(self, size_bytes):
        """Chamado pela rede a cada mensagem enviada."""
        self.bytes_by_time[self.env.now] += size_bytes

    def on_informed(self):
        """Chamado quando um nó obtém a atualização pela primeira vez."""
        self.informed += 1
        self.coverage_events.append((self.env.now, self.informed / self.cohort))
        for percent, crossed_at in self.crossing_ms.items():
            # Comparação com inteiros: evita erro de arredondamento em 0.95 * n.
            if crossed_at is None and self.informed * 100 >= percent * self.cohort:
                self.crossing_ms[percent] = self.env.now

    def on_duplicate(self):
        """Chamado quando uma mensagem entregue não traz informação nova."""
        self.duplicates += 1

    def coverage_curve(self, step_ms=500):
        """Cobertura amostrada a cada `step_ms`, de 0 até o instante atual.

        Devolve uma lista de (instante, cobertura). O valor em cada instante é
        a cobertura depois de todos os eventos ocorridos até ele.
        """
        curve, i, coverage = [], 0, 0.0
        for t in range(0, self.env.now + 1, step_ms):
            while i < len(self.coverage_events) and self.coverage_events[i][0] <= t:
                coverage = self.coverage_events[i][1]
                i += 1
            curve.append((t, coverage))
        return curve

    def summary(self):
        """Linha de resumo da execução; vira uma linha do `summary_df`."""
        nan = float("nan")
        t50, t95 = self.crossing_ms[50], self.crossing_ms[95]
        return {
            "coverage_final": self.informed / self.cohort,
            "t50_ms": nan if t50 is None else t50,
            "t95_ms": nan if t95 is None else t95,
            "bytes_total": sum(self.bytes_by_time.values()),
            "bytes_until_t95": nan
            if t95 is None
            else sum(b for t, b in self.bytes_by_time.items() if t <= t95),
            "duplicates": self.duplicates,
        }
