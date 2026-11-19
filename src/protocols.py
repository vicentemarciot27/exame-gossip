"""Protocolos Gossip decidem o que enviar e o que fazer ao receber."""

from __future__ import annotations

from dataclasses import dataclass


HEADER_BYTES = 16  # cabeçalho de toda mensagem


@dataclass(frozen=True)
class Message:
    version: int  # versão da atualização que o remetente possui
    size_bytes: int  # tamanho cobrado no envio: cabeçalho + conteúdo


class Push:
    def __init__(self, network, rng, metrics, fanout, payload_bytes):
        self.network = network
        self.rng = rng  # numpy Generator usado somente para sortear peers
        self.metrics = metrics  # recebe primeiras recepções e duplicatas
        self.fanout = fanout  # quantos peers recebem a mensagem por rodada
        # Tamanho de uma mensagem DATA, que carrega a atualização inteira.
        self.data_bytes = HEADER_BYTES + payload_bytes

    def on_round(self, node):
        """Chamado pela simulação a cada rodada de gossip do nó."""
        if node.version == 0:
            return  # quem não tem a atualização não tem o que enviar
        # sample_peers limita o sorteio ao número de peers do nó.
        for dst in self.network.sample_peers(node.id, self.fanout, self.rng):
            self.network.send(node.id, dst, Message(node.version, self.data_bytes))

    def on_message(self, node, src, message):
        """Chamado pela rede quando uma mensagem chega ao nó."""
        if message.version > node.version:
            node.version = message.version
            self.metrics.on_informed()  # primeira recepção: a cobertura sobe
        else:
            node.duplicates += 1  # estatística local do nó
            self.metrics.on_duplicate()  # total da execução
