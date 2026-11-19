"""Contadores de uma execução. Só observam: nenhum nó decide com base neles.

Definições de cada métrica no README, seção "Especificação do modelo".
"""

from __future__ import annotations

from collections import Counter


class Metrics:
    def __init__(self, env, n_nodes):
        self.env = env  # só para ler env.now
        # coorte = nós online, denominador da cobertura; sem churn, todos
        self.cohort = n_nodes
        self.informed = 0  # nós da coorte com a atualização
        self.coverage_events = [(0, 0.0)]  # (instante, cobertura) a cada mudança
        self.crossing_ms = {50: None, 95: None}  # T50 e T95; None = ainda não cruzou
        self.bytes_by_time = Counter()  # instante do envio -> bytes
        self.bytes_control = 0  # só DIGEST
        self.bytes_repair = 0  # DATA enviada em resposta a um DIGEST
        self.duplicates = 0
        self.timeouts = 0  # trocas de anti-entropy sem resposta
        self.budget_drops = 0  # envios barrados por falta de saldo

    def on_send(self, size_bytes, kind="DATA", reply=False):
        self.bytes_by_time[self.env.now] += size_bytes
        if kind == "DIGEST":
            self.bytes_control += size_bytes
        elif reply:
            self.bytes_repair += size_bytes

    def on_timeout(self):
        self.timeouts += 1

    def on_budget_drop(self):
        self.budget_drops += 1

    def on_informed(self):
        """Primeira vez que um nó obtém a atualização."""
        self.informed += 1
        self._record_coverage()

    def on_cohort_change(self, cohort_delta, informed_delta):
        """Churn: nós entraram ou saíram da coorte.

        `informed_delta` é a variação de nós da coorte que têm a atualização.
        """
        self.cohort += cohort_delta
        self.informed += informed_delta
        self._record_coverage()

    def _record_coverage(self):
        self.coverage_events.append((self.env.now, self.informed / self.cohort))
        for percent, crossed_at in self.crossing_ms.items():
            # inteiros: 0.95 * n em float pode arredondar errado
            if crossed_at is None and self.informed * 100 >= percent * self.cohort:
                self.crossing_ms[percent] = self.env.now

    def on_duplicate(self):
        """DATA entregue sem informação nova."""
        self.duplicates += 1

    def coverage_curve(self, step_ms=500):
        """Lista de (instante, cobertura) a cada `step_ms`, de 0 até agora.

        Cada ponto inclui todos os eventos ocorridos até aquele instante.
        """
        curve, i, coverage = [], 0, 0.0
        for t in range(0, self.env.now + 1, step_ms):
            while i < len(self.coverage_events) and self.coverage_events[i][0] <= t:
                coverage = self.coverage_events[i][1]
                i += 1
            curve.append((t, coverage))
        return curve

    def summary(self):
        """Uma linha do `summary_df`."""
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
            "bytes_control": self.bytes_control,
            "bytes_repair": self.bytes_repair,
            "duplicates": self.duplicates,
            "timeouts": self.timeouts,
            "budget_drops": self.budget_drops,
        }
