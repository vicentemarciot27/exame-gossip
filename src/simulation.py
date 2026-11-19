"""Monta e executa uma simulação a partir de uma configuração e de uma seed."""

from __future__ import annotations

from functools import partial

import numpy as np
import simpy

from src.metrics import Metrics
from src.network import Network
from src.protocols import Push


class Node:
    """Estado local de um nó. Não contém lógica de protocolo."""

    def __init__(self, node_id):
        self.id = node_id
        self.version = 0  # 0 = ainda não recebeu a atualização
        self.duplicates = 0  # mensagens recebidas sem informação nova


class Simulation:
    def __init__(self, config, seed):
        self.config = config
        self.env = simpy.Environment()
        n = config["network"]["nodes"]

        # Um gerador aleatório independente por componente, todos derivados
        # da mesma seed. Novos componentes entram no fim desta lista.
        network_rng, protocol_rng, injection_rng = (
            np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(3)
        )

        assert config["network"]["topology"] == "complete", "topologia não suportada"
        self.metrics = Metrics(self.env, n)
        self.network = Network(
            self.env, n, network_rng, self.metrics, tuple(config["network"]["latency_ms"])
        )
        self.protocol = Push(
            self.network,
            protocol_rng,
            self.metrics,
            fanout=config["protocol"]["fanout"],
            payload_bytes=config["update"]["size_bytes"],
        )

        self.nodes = [Node(i) for i in range(n)]
        for node in self.nodes:
            # partial fixa `node` agora; a rede chama handler(src, message).
            self.network.register(node.id, partial(self.protocol.on_message, node))
            self.env.process(self._gossip_loop(node))

        # Injeta a atualização: os nós sorteados começam com a versão 1.
        initial = config["update"]["initial_infected"]
        for i in injection_rng.choice(n, size=initial, replace=False).tolist():
            self.nodes[i].version = 1
            self.metrics.on_informed()

    def _gossip_loop(self, node):
        interval = self.config["simulation"]["gossip_interval_ms"]
        while True:
            yield self.env.timeout(interval)
            self.protocol.on_round(node)

    def run(self):
        """Executa até `duration_ms` e devolve a linha de resumo das métricas."""
        self.env.run(until=self.config["simulation"]["duration_ms"])
        return self.metrics.summary()
