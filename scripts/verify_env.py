"""
AETHER Phase 0 environment gate.

Answers three questions before any code is written:
  1. Does the interpreter meet the floor?
  2. Does every dependency the deterministic core needs actually import?
  3. Can this machine reach the Anthropic API over TLS?

Question 3 is expected to fail on networks with TLS interception. That is not a
blocker: it decides whether the Legal-Clause Agent runs in `live` or `replay`
mode for the demo, and the demo must work either way.

Run:  python scripts/verify_env.py
Exit: 0 if the core stack is usable (regardless of connectivity), 1 otherwise.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import socket
import ssl
import sys
from dataclasses import dataclass, field
from typing import Literal

MIN_PYTHON = (3, 12)
ANTHROPIC_HOST = "api.anthropic.com"

Status = Literal["ok", "warn", "fail"]

GLYPH = {"ok": "PASS", "warn": "WARN", "fail": "FAIL"}

# (module, why the project needs it, required-for-core)
DEPENDENCIES: list[tuple[str, str, bool]] = [
    ("numpy", "curve math, SIMM aggregation", True),
    ("scipy", "collateral optimisation LP (HiGHS)", True),
    ("pydantic", "typed contracts at every boundary", True),
    ("fastapi", "API layer", False),
    ("uvicorn", "ASGI server", False),
    ("sqlmodel", "persistence", False),
    ("pytest", "test runner", False),
    ("hypothesis", "property-based invariants", False),
    ("anthropic", "Legal-Clause Agent (live mode only)", False),
    ("certifi", "CA bundle for TLS on intercepted networks", False),
    ("truststore", "OS trust store bridge, TLS fallback", False),
]


@dataclass
class Check:
    name: str
    status: Status
    detail: str
    remedy: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: Status, detail: str, remedy: str = "") -> None:
        self.checks.append(Check(name, status, detail, remedy))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == "fail"]

    @property
    def warned(self) -> list[Check]:
        return [c for c in self.checks if c.status == "warn"]


def check_python(report: Report) -> None:
    v = sys.version_info
    label = f"{v.major}.{v.minor}.{v.micro} ({platform.machine()})"
    if (v.major, v.minor) >= MIN_PYTHON:
        report.add("python", "ok", label)
    else:
        report.add(
            "python",
            "fail",
            f"{label} is below the {MIN_PYTHON[0]}.{MIN_PYTHON[1]} floor",
            "Install a newer interpreter.",
        )


def check_dependencies(report: Report) -> None:
    for module, why, core in DEPENDENCIES:
        try:
            mod = importlib.import_module(module)
        except ImportError:
            report.add(
                f"dep:{module}",
                "fail" if core else "warn",
                f"not installed - {why}",
                f"pip install {module}",
            )
            continue
        version = getattr(mod, "__version__", "unknown")
        report.add(f"dep:{module}", "ok", f"{version} - {why}")


def _tls_probe(host: str, context: ssl.SSLContext) -> tuple[bool, str]:
    """Open a TLS connection and report the peer's issuer, or the failure."""
    try:
        with (
            socket.create_connection((host, 443), timeout=10) as raw,
            context.wrap_socket(raw, server_hostname=host) as tls,
        ):
            cert = tls.getpeercert() or {}
            issuer = dict(x[0] for x in cert.get("issuer", ()))
            name = issuer.get("organizationName") or issuer.get("commonName") or "unknown"
            return True, f"{tls.version()}, issued by {name}"
    except ssl.SSLCertVerificationError as exc:
        return False, f"certificate verification failed: {exc.verify_message or exc}"
    except (TimeoutError, OSError) as exc:
        return False, f"connection failed: {exc}"


def check_connectivity(report: Report) -> None:
    """Probe TLS three ways: default trust, certifi, then truststore."""
    ok, detail = _tls_probe(ANTHROPIC_HOST, ssl.create_default_context())
    if ok:
        report.add("tls:default", "ok", f"{ANTHROPIC_HOST} - {detail}")
        return

    report.add("tls:default", "warn", f"{ANTHROPIC_HOST} - {detail}")

    # Fallback 1: certifi's bundle.
    try:
        import certifi

        ok, detail = _tls_probe(ANTHROPIC_HOST, ssl.create_default_context(cafile=certifi.where()))
        report.add(
            "tls:certifi",
            "ok" if ok else "warn",
            detail,
            "" if ok else "Intercepting CA is not in certifi's bundle.",
        )
        if ok:
            report.add(
                "tls:resolution",
                "ok",
                "reachable via certifi",
                "Set SSL_CERT_FILE=$(python -m certifi) for the API process.",
            )
            return
    except ImportError:
        report.add("tls:certifi", "warn", "certifi not installed, skipped")

    # Fallback 2: the OS trust store, which holds the intercepting CA if one is installed.
    try:
        import truststore

        ok, detail = _tls_probe(ANTHROPIC_HOST, truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
        report.add("tls:truststore", "ok" if ok else "warn", detail)
        if ok:
            report.add(
                "tls:resolution",
                "ok",
                "reachable via OS trust store",
                "Call truststore.inject_into_ssl() at API startup.",
            )
            return
    except ImportError:
        report.add("tls:truststore", "warn", "truststore not installed, skipped")

    report.add(
        "tls:resolution",
        "warn",
        "no working TLS path to the Anthropic API",
        "Demo runs in AETHER_MODE=replay. Live extraction unavailable on this network.",
    )


def check_api_key(report: Report) -> None:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        report.add("api_key", "ok", f"present ({len(key)} chars)")
    else:
        report.add(
            "api_key",
            "warn",
            "ANTHROPIC_API_KEY unset",
            "Only required for AETHER_MODE=live. Replay mode needs no key.",
        )


def check_decimal_policy(report: Report) -> None:
    """The money invariant, asserted rather than assumed."""
    from decimal import ROUND_HALF_EVEN, Decimal, getcontext

    getcontext().prec = 28
    probe = (Decimal("0.1") + Decimal("0.2")).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    if probe == Decimal("0.30") and (0.1 + 0.2) != 0.3:
        report.add("decimal", "ok", "exact arithmetic confirmed, float drift confirmed")
    else:
        report.add(
            "decimal",
            "fail",
            "unexpected Decimal behaviour",
            "Investigate before building core/.",
        )


def render(report: Report) -> None:
    width = max(len(c.name) for c in report.checks) + 2
    print("\n  AETHER - Phase 0 environment gate")
    print("  " + "-" * 62)
    for c in report.checks:
        print(f"  {GLYPH[c.status]}  {c.name:<{width}} {c.detail}")
        if c.remedy:
            print(f"        {'':<{width}} -> {c.remedy}")
    print("  " + "-" * 62)

    resolved = any(c.name == "tls:resolution" and c.status == "ok" for c in report.checks)
    mode = "live" if resolved else "replay"
    if any(c.name == "tls:default" and c.status == "ok" for c in report.checks):
        mode = "live"

    print(
        f"  {len(report.checks) - len(report.failed) - len(report.warned)} passed, "
        f"{len(report.warned)} warned, {len(report.failed)} failed"
    )
    print(f"  Demo mode available: AETHER_MODE={mode}")
    if mode == "replay":
        print("  Replay mode is fully sufficient for the demo. Live extraction is optional.")
    print()


def main() -> int:
    report = Report()
    check_python(report)
    check_dependencies(report)
    check_decimal_policy(report)
    check_api_key(report)
    check_connectivity(report)
    render(report)

    if "--json" in sys.argv:
        print(json.dumps([c.__dict__ for c in report.checks], indent=2))

    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
