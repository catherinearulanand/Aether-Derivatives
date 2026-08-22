"""AI governance, supervision and evidence.

This package sits **outside** ``aether.core``. Nothing here is imported by the
deterministic engine, and nothing here computes a financial value: it decides who
may ask for a calculation, records which model produced an interpretation, and
assembles the evidence that proves what happened.

.. rubric:: The principle these modules enforce

    AI interprets → deterministic engines calculate → optimisation proposes →
    humans authorise → cryptographic evidence proves what happened.

Each module owns one clause of that sentence:

``registry``     which model, version and policy produced an output
``authority``    what each component is permitted to do, checked server-side
``sanitise``     document content is data, never instruction
``escalation``   how much scrutiny a decision attracts
``supervision``  who may propose and who may approve, and that they differ
``integrity``    what must hold before a workflow may proceed
``evidence``     the record that lets a supervisor reconstruct a decision

.. rubric:: What this package does not claim

No module here asserts regulatory compliance, approval or certification. What is
implemented is a set of technical controls designed to *support* supervision:
attributable AI, enforced separation of duties, tamper-evident lineage and
exportable evidence. Whether those controls satisfy a given jurisdiction is a
question for a reviewer with authority to answer it, and the control mapping in
``docs/control-mapping.yaml`` is written to be filled in by that reviewer rather
than pre-answered here.
"""

from __future__ import annotations

__all__ = [
    "authority",
    "escalation",
    "evidence",
    "integrity",
    "registry",
    "sanitise",
    "supervision",
]
