"""Este módulo é o único lugar que entrega mensagens. Os protocolos chamam
`Network.send`; a rede decide quando a mensagem chega ao destino.
"""

from __future__ import annotations


class Network:
    def __init__(self, env, n, rng, metrics, latency_ms=(10, 10)):
        self.env = env  # simpy.Environment: relógio e fila de eventos
        # Número de nós. A topologia é completa e implícita: todo nó é vizinho
        # de todos os outros, então nenhuma lista de arestas fica na memória.
        self.n = n
        self.rng = rng  # numpy Generator usado somente pelo transporte
        self.metrics = metrics  # recebe os bytes de cada mensagem enviada
        self.latency_ms = latency_ms  # (mínimo, máximo), em ms inteiros
        self.handlers = {}  # id do nó -> função chamada na entrega

    def register(self, node_id, handler):
        """Associa ao nó a função `handler(src, message)` chamada na entrega."""
        self.handlers[node_id] = handler

    def sample_peers(self, node_id, k, rng):
        """Sorteia até `k` vizinhos distintos de `node_id`, com o `rng` de quem chama.

        O custo depende de `k`, não de `n`: a lista de vizinhos nunca é montada.
        """
        # Os vizinhos de `node_id` são os outros n-1 nós. Sorteia posições em
        # 0..n-2 e soma 1 às posições >= node_id, o que pula o próprio nó.
        picks = rng.choice(self.n - 1, size=min(k, self.n - 1), replace=False)
        return (picks + (picks >= node_id)).tolist()

    def send(self, src, dst, message):
        """Agenda a entrega de `message` de `src` para `dst`"""
        assert src != dst and 0 <= dst < self.n, f"{src} e {dst} não são vizinhos"
        # Os bytes contam no envio, mesmo que a mensagem não chegue a ser entregue.
        self.metrics.on_send(message.size_bytes)
        low, high = self.latency_ms
        delay = int(self.rng.integers(low, high + 1))
        # Toda mensagem tem seu pŕoprio processo SimPY
        # trocar por callback no Timeout se demorar demais.
        self.env.process(self._deliver(src, dst, message, delay))

    def _deliver(self, src, dst, message, delay):
        yield self.env.timeout(delay)  # espera `delay` ms simulados
        self.handlers[dst](src, message)
