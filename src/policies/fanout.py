"""Políticas de fanout: quantos peers o nó contata por rodada de gossip.

A adaptativa usa só o que o nó vê: as DATA que recebeu e o resultado das
trocas de anti-entropy que abriu. Regras no README, seções "Fanout adaptativo"
e "Quiescência após saturação local".
"""

from __future__ import annotations

from collections import deque

TIMEOUT_WINDOW = 5  # últimas trocas de anti-entropy na fração de timeouts


class FixedFanout:
    def __init__(self, fanout):
        self.value = fanout

    def fanout(self, node):
        return self.value

    def on_ae_result(self, node, result):
        pass

    def on_newer_version(self, node):
        pass


class AdaptiveFanout:
    def __init__(
        self,
        n,
        min_fanout,
        max_fanout,
        duplicate_threshold,
        timeout_threshold,
        quiescence_rounds=None,
    ):
        self.min_fanout = min_fanout
        self.max_fanout = max_fanout
        self.duplicate_threshold = duplicate_threshold
        self.timeout_threshold = timeout_threshold
        self.quiescence_rounds = quiescence_rounds  # None = sem quiescência
        # estado por nó, indexado pelo id
        self.current = [max_fanout] * n  # começa no máximo
        self.seen_received = [0] * n  # node.received na rodada anterior
        self.seen_duplicates = [0] * n  # node.duplicates na rodada anterior
        # últimas trocas de anti-entropy, True = timeout
        self.ae_timeouts = [deque(maxlen=TIMEOUT_WINDOW) for _ in range(n)]
        self.saturation_count = [0] * n  # rodadas com evidência de saturação
        self.same_version_seen = [False] * n  # anti-entropy achou peer na mesma versão

    def fanout(self, node):
        """Chamado a cada rodada de um nó que já tem a atualização."""
        i = node.id
        # delta desde a rodada anterior
        received = node.received - self.seen_received[i]
        duplicates = node.duplicates - self.seen_duplicates[i]
        self.seen_received[i] = node.received
        self.seen_duplicates[i] = node.duplicates
        if received and duplicates / received > self.duplicate_threshold:
            self.current[i] = max(self.min_fanout, self.current[i] - 1)

        if self.quiescence_rounds:
            if duplicates or self.same_version_seen[i]:
                self.saturation_count[i] += 1
            self.same_version_seen[i] = False
            if self.saturation_count[i] >= self.quiescence_rounds:
                return 0  # quiescente: para o Push, a anti-entropy continua
        return self.current[i]

    def on_ae_result(self, node, result):
        """`result`: "timeout", "newer", "same" ou "older", a versão do peer
        em relação à do nó.
        """
        i = node.id
        window = self.ae_timeouts[i]
        window.append(result == "timeout")
        if sum(window) / len(window) > self.timeout_threshold:
            self.current[i] = min(self.max_fanout, self.current[i] + 1)
        if result == "same":
            self.same_version_seen[i] = True
        elif result == "older":
            self.saturation_count[i] = 0  # tem peer atrasado: volta a fazer Push

    def on_newer_version(self, node):
        self.saturation_count[node.id] = 0
        self.same_version_seen[node.id] = False
