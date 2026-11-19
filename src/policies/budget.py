"""Teto de bytes que cada nó envia por janela de tempo."""

from __future__ import annotations


class Budget:
    def __init__(self, env, n, bytes_per_interval, interval_ms):
        self.env = env
        self.limit = bytes_per_interval  # por nó, por janela
        self.interval_ms = interval_ms
        # por nó: janela do último envio e bytes gastos nela
        self.window = [0] * n
        self.spent = [0] * n

    def try_spend(self, node_id, size_bytes):
        """Debita `size_bytes` do saldo do nó. False se não há saldo.

        Janelas fixas: a janela k cobre [k * interval_ms, (k + 1) * interval_ms).
        O saldo zera no primeiro envio do nó numa janela nova, então não precisa
        de processo periódico.
        """
        window = self.env.now // self.interval_ms
        if self.window[node_id] != window:
            self.window[node_id] = window
            self.spent[node_id] = 0
        if self.spent[node_id] + size_bytes > self.limit:
            return False
        self.spent[node_id] += size_bytes
        return True
