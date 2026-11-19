"""Monta e executa uma simulação a partir de uma configuração e de uma seed."""

from __future__ import annotations

from functools import partial

import numpy as np
import simpy

from src.metrics import Metrics
from src.network import Network, random_regular_neighbors
from src.policies.budget import Budget
from src.policies.fanout import AdaptiveFanout, FixedFanout
from src.protocols import Push, PushPull

PROTOCOLS = {"push": Push, "push_pull": PushPull}


class Node:
    """Estado local de um nó, sem lógica de protocolo."""

    def __init__(self, node_id):
        self.id = node_id
        self.version = 0  # 0 = sem a atualização
        self.received = 0  # DATA recebidas
        self.duplicates = 0  # DATA recebidas sem nada novo
        self.ae_peer = None  # peer da troca de anti-entropy ainda sem resposta


class Simulation:
    def __init__(self, config, seed):
        self.config = config
        self.env = simpy.Environment()
        net = config["network"]
        n = net["nodes"]

        # um gerador por componente, todos da mesma seed: mudar um componente
        # não mexe nos sorteios dos outros. componente novo entra no fim da
        # lista, senão os streams existentes mudam
        network_rng, protocol_rng, injection_rng, loss_rng, churn_rng, topology_rng = (
            np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(6)
        )

        assert net["topology"] in ("complete", "random_regular_connected")
        neighbors = None  # rede completa
        if net["topology"] == "random_regular_connected":
            neighbors = random_regular_neighbors(n, net["degree"], topology_rng)

        self.metrics = Metrics(self.env, n)
        budget = Budget(
            self.env,
            n,
            config["budget"]["bytes_per_node_per_interval"],
            config["budget"]["interval_ms"],
        )
        self.network = Network(
            self.env,
            n,
            network_rng,
            self.metrics,
            latency_ms=tuple(net["latency_ms"]),
            neighbors=neighbors,
            packet_loss=net["packet_loss"],
            loss_rng=loss_rng,
            budget=budget,
        )
        protocol = config["protocol"]
        # `adaptive` presente = AdaptiveFanout; `fanout` é ignorado
        if protocol.get("adaptive"):
            policy = AdaptiveFanout(n, **protocol["adaptive"])
        else:
            policy = FixedFanout(protocol["fanout"])
        self.protocol = PROTOCOLS[protocol["name"]](
            self.network,
            protocol_rng,
            self.metrics,
            policy,
            payload_bytes=config["update"]["size_bytes"],
        )
        self.nodes = [Node(i) for i in range(n)]

        initial = config["update"]["initial_infected"]
        origins = injection_rng.choice(n, size=initial, replace=False).tolist()
        for i in origins:
            self.nodes[i].version = 1
            self.metrics.on_informed()

        # processos de falha antes dos laços de gossip: no mesmo instante,
        # o estado da rede muda antes das rodadas e das entregas
        if net["churn_fraction"] > 0:
            self.env.process(self._churn_loop(churn_rng, origins))
        if net["partition"]:
            self.env.process(self._partition(**net["partition"]))

        gossip_interval = config["simulation"]["gossip_interval_ms"]
        ae_interval = protocol["ae_interval_ms"]  # None = sem anti-entropy
        for node in self.nodes:
            self.network.register(node.id, partial(self.protocol.on_message, node))

        # um processo por intervalo, não por nó: um evento por tick na fila em
        # vez de N. intervalos iguais compartilham o processo, então rodada de
        # gossip e tick de anti-entropy de cada nó rodam em sequência
        ticks = {gossip_interval: [self.protocol.on_round]}
        if ae_interval:
            ticks.setdefault(ae_interval, []).append(self.protocol.on_ae_round)
        for interval_ms, actions in ticks.items():
            self.env.process(self._periodic(interval_ms, actions))

    def _periodic(self, interval_ms, actions):
        """A cada `interval_ms`, roda `actions` em cada nó online, em ordem de id."""
        online = self.network.online
        while True:
            yield self.env.timeout(interval_ms)
            for node in self.nodes:
                if online[node.id]:
                    for action in actions:
                        action(node)

    def _churn_loop(self, rng, origins):
        """Mantém `churn_fraction` dos nós offline; ressorteia a cada período."""
        net = self.config["network"]
        n = len(self.nodes)
        k = int(net["churn_fraction"] * n)
        # origem nunca cai: offline ela não roda rodadas e o gossip pode não começar
        candidates = [i for i in range(n) if i not in origins]
        online = self.network.online
        offline = []
        while True:
            returning = offline
            offline = rng.choice(candidates, size=k, replace=False).tolist()
            for i in returning:
                online[i] = True
            for i in offline:
                online[i] = False
            # nó sorteado em dois períodos seguidos entra nas duas somas e
            # se cancela
            self.metrics.on_cohort_change(
                cohort_delta=len(returning) - len(offline),
                informed_delta=sum(self.nodes[i].version > 0 for i in returning)
                - sum(self.nodes[i].version > 0 for i in offline),
            )
            yield self.env.timeout(net["churn_period_ms"])

    def _partition(self, groups, start_ms, end_ms):
        """Isola os grupos `node_id % groups` entre `start_ms` e `end_ms`."""
        yield self.env.timeout(start_ms)
        self.network.partition_groups = groups
        yield self.env.timeout(end_ms - start_ms)
        self.network.partition_groups = 0

    def run(self):
        """Roda até `duration_ms` e devolve a linha de resumo."""
        self.env.run(until=self.config["simulation"]["duration_ms"])
        summary = self.metrics.summary()
        # recuperação = T95 - fim da partição; NaN sem partição ou sem T95
        partition = self.config["network"]["partition"]
        end_ms = partition["end_ms"] if partition else float("nan")
        summary["recovery_ms"] = summary["t95_ms"] - end_ms
        return summary
