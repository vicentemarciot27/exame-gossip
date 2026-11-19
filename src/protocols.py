"""Protocolos Gossip: o que enviar e o que fazer ao receber.

Trocas de mensagens no README, seção "Mensagens e protocolos".
"""

from __future__ import annotations

from dataclasses import dataclass

HEADER_BYTES = 16


@dataclass(frozen=True)
class Message:
    version: int  # versão que o remetente tem
    size_bytes: int  # cobrado no envio: cabeçalho + conteúdo
    kind: str = "DATA"  # DATA carrega a atualização; DIGEST só a versão
    reply: bool = False  # resposta a um DIGEST
    ae: bool = False  # parte de uma troca de anti-entropy


class Push:
    def __init__(self, network, rng, metrics, policy, payload_bytes):
        self.network = network
        self.rng = rng  # só sorteio de peers
        self.metrics = metrics
        self.policy = policy  # policies.fanout: quantos peers por rodada
        self.data_bytes = HEADER_BYTES + payload_bytes  # DATA leva a atualização inteira

    def _send(self, node, dst, kind, **flags):
        """Envia a versão atual do nó. False se o orçamento barrou."""
        size = self.data_bytes if kind == "DATA" else HEADER_BYTES
        message = Message(node.version, size, kind, **flags)
        return self.network.send(node.id, dst, message)

    def on_round(self, node):
        if node.version == 0:
            return
        fanout = self.policy.fanout(node)
        # sample_peers já corta o fanout no número de vizinhos
        for dst in self.network.sample_peers(node.id, fanout, self.rng):
            self._send(node, dst, "DATA")

    def on_ae_round(self, node):
        if node.ae_peer is not None:
            # a troca do tick anterior ficou sem resposta
            self.metrics.on_timeout()
            self.policy.on_ae_result(node, "timeout")
        (peer,) = self.network.sample_peers(node.id, 1, self.rng)
        sent = self._send(node, peer, "DIGEST", ae=True)
        # DIGEST barrado pelo orçamento não abre troca, senão viraria timeout falso
        node.ae_peer = peer if sent else None

    def on_message(self, node, src, message):
        # resposta à troca de anti-entropy que este nó abriu?
        answered = message.ae and message.reply and src == node.ae_peer
        if answered:
            node.ae_peer = None

        if message.kind == "DATA":
            node.received += 1
            if message.version > node.version:
                node.version = message.version
                self.metrics.on_informed()
                self.policy.on_newer_version(node)
            else:
                node.duplicates += 1  # contador local, usado pelo fanout adaptativo
                self.metrics.on_duplicate()
            if answered:
                self.policy.on_ae_result(node, "newer")
        elif message.reply:
            # DIGEST de resposta: o peer não tinha nada mais novo.
            # se o dele é mais antigo, manda a atualização
            older = message.version < node.version
            if older:
                self._send(node, src, "DATA", reply=True, ae=True)
            if answered:
                self.policy.on_ae_result(node, "older" if older else "same")
        elif node.version > message.version:
            # pedido de quem está atrás: responde com DATA
            self._send(node, src, "DATA", reply=True, ae=message.ae)
        elif message.ae:
            # nada mais novo: responde só com a versão, para não virar timeout.
            # pedido do Push-Pull nessa situação fica sem resposta
            self._send(node, src, "DIGEST", reply=True, ae=True)


class PushPull(Push):
    """Push, mais pull de quem ainda não tem a atualização."""

    def on_round(self, node):
        if node.version > 0:
            return super().on_round(node)
        fanout = self.policy.fanout(node)
        for dst in self.network.sample_peers(node.id, fanout, self.rng):
            self._send(node, dst, "DIGEST")
