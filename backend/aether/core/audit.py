"""Audit trail — quantitative function F12.

An append-only, hash-chained record of everything the pipeline did.

.. rubric:: How the chain works

Each event's hash covers both its own canonical content and the previous event's
hash::

    h_n = SHA256( h_{n-1} || canonical_json(event_n) )

Altering any historical event changes its hash, which breaks every hash after it.
:meth:`AuditChain.verify` recomputes the whole chain and reports the first index
where it diverges. That makes the log **tamper-evident**: it does not prevent
modification, it makes modification detectable.

.. rubric:: What this is not

This is not a blockchain. There is no distributed consensus, no proof of work, and
no immutability guarantee beyond "someone would have to rewrite every subsequent
hash". A hash chain is the right tool for a single-writer audit log and claiming
more than that would be dishonest.

.. rubric:: Canonicalisation

Hashing requires one byte sequence per logical value, so the serialiser sorts keys,
uses compact separators, and renders every :class:`~decimal.Decimal` as a string. A
float never reaches the hash — floats are exactly the values whose repr can vary.

``json`` and ``hashlib`` are used here and are permitted in the deterministic core:
neither performs I/O, and both are pure functions of their input.

Part of the deterministic core: no I/O, no network, no clock, no framework
dependency. Timestamps are passed in explicitly, never read from the system.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from aether.core.money import Money

__all__ = [
    "GENESIS_HASH",
    "ActorType",
    "AuditChain",
    "AuditEvent",
    "canonical_json",
]

#: The hash a chain starts from. Sixty-four zeros, so the first link is unambiguous.
GENESIS_HASH = "0" * 64


class ActorType(StrEnum):
    """Who or what performed an action.

    The distinction is load-bearing: the audit trail must show at a glance which
    values came from a model, which from a deterministic engine, and which from a
    human. That is the product's central claim, recorded as data.
    """

    ENGINE = "ENGINE"
    AGENT = "AGENT"
    HUMAN = "HUMAN"
    SYSTEM = "SYSTEM"


def _encode(value: Any) -> Any:
    """Reduce a value to JSON-safe primitives, deterministically.

    Decimal becomes a string rather than a float so no precision is lost and no
    platform-dependent repr can creep into a hash.
    """
    if isinstance(value, Money):
        return {"amount": str(value.amount), "currency": value.currency.value}
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_encode(v) for v in value]
    if isinstance(value, float):
        raise TypeError(
            f"Refusing to hash a float ({value}). Convert to Decimal or str first — "
            "float repr is not stable enough to hash."
        )
    if value is None or isinstance(value, str | int | bool):
        return value
    raise TypeError(f"Cannot canonicalise {type(value).__name__} for the audit chain.")


def canonical_json(payload: Any) -> str:
    """Deterministic JSON: sorted keys, compact separators, no floats."""
    return json.dumps(
        _encode(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One tamper-evident record."""

    seq: int
    actor: str
    actor_type: ActorType
    action: str
    entity_type: str
    entity_id: str
    occurred_at: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str

    def recompute_hash(self) -> str:
        """Recompute this event's hash from its content and its predecessor."""
        body = canonical_json(
            {
                "seq": self.seq,
                "actor": self.actor,
                "actor_type": self.actor_type.value,
                "action": self.action,
                "entity_type": self.entity_type,
                "entity_id": self.entity_id,
                "occurred_at": self.occurred_at,
                "payload": self.payload,
            }
        )
        return hashlib.sha256((self.prev_hash + body).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AuditChain:
    """An immutable append-only chain.

    ``append`` returns a new chain rather than mutating this one, so an audit trail
    cannot be edited in place by accident.
    """

    chain_id: str
    events: tuple[AuditEvent, ...] = ()

    @property
    def head_hash(self) -> str:
        return self.events[-1].hash if self.events else GENESIS_HASH

    def append(
        self,
        *,
        actor: str,
        actor_type: ActorType,
        action: str,
        entity_type: str,
        entity_id: str,
        occurred_at: str,
        payload: dict[str, Any] | None = None,
    ) -> AuditChain:
        """Return a new chain with one more event linked onto the head.

        ``occurred_at`` is supplied by the caller. The core never reads a clock, so
        an identical pipeline run produces an identical chain — which is what makes
        the determinism test possible.
        """
        seq = len(self.events)
        prev_hash = self.head_hash

        draft = AuditEvent(
            seq=seq,
            actor=actor,
            actor_type=actor_type,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            occurred_at=occurred_at,
            payload=dict(payload or {}),
            prev_hash=prev_hash,
            hash="",
        )
        linked = AuditEvent(
            seq=draft.seq,
            actor=draft.actor,
            actor_type=draft.actor_type,
            action=draft.action,
            entity_type=draft.entity_type,
            entity_id=draft.entity_id,
            occurred_at=draft.occurred_at,
            payload=draft.payload,
            prev_hash=draft.prev_hash,
            hash=draft.recompute_hash(),
        )
        return AuditChain(chain_id=self.chain_id, events=(*self.events, linked))

    def verify(self) -> tuple[bool, int | None, str]:
        """Recompute the chain. Returns ``(valid, break_index, message)``."""
        expected_prev = GENESIS_HASH

        for index, event in enumerate(self.events):
            if event.seq != index:
                return (
                    False,
                    index,
                    f"Event {index} claims sequence {event.seq}. The chain has a gap "
                    f"or has been reordered.",
                )
            if event.prev_hash != expected_prev:
                return (
                    False,
                    index,
                    f"Event {index} points at {event.prev_hash[:12]}... but the "
                    f"previous event hashes to {expected_prev[:12]}...",
                )
            if event.recompute_hash() != event.hash:
                return (
                    False,
                    index,
                    f"Event {index} ({event.action}) does not match its own hash. "
                    f"Its content has been altered since it was written.",
                )
            expected_prev = event.hash

        return True, None, f"All {len(self.events)} events verify against the chain."

    def __len__(self) -> int:
        return len(self.events)
