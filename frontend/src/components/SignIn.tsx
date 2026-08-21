"use client";

import { Chip } from "@/components/primitives";
import {
  PERMISSION_LABELS,
  ROLES,
  ROLE_PROFILES,
  can,
  type Permission,
  type Role,
} from "@/lib/roles";
import { useAether } from "@/lib/store";
import { useState, useSyncExternalStore } from "react";

/**
 * Role selection.
 *
 * .. rubric:: An honest gate
 *
 * There is no password here, and the screen says so. What this demonstrates is
 * **separation of duties** — that the person who interprets the contract is not
 * the person who signs off the money it produces, and that an auditor can read
 * everything and change nothing.
 *
 * Each card states what the role cannot do as prominently as what it can, because
 * on a collateral platform the restrictions are the design. The one permission
 * that matters most, approval, is refused by the API as well as by this UI: a
 * gate that lives only in the browser is decoration.
 */
export function SignIn() {
  const signIn = useAether((s) => s.signIn);
  const [focused, setFocused] = useState<Role>("RISK");

  return (
    <div className="min-h-screen flex items-center justify-center p-5">
      <div className="w-full max-w-[1040px] flex flex-col gap-5">
        <header className="flex flex-col gap-2.5">
          <div className="flex items-baseline gap-3">
            <span
              className="mono font-bold"
              style={{ color: "var(--accent)", letterSpacing: "0.28em", fontSize: 19 }}
            >
              AETHER
            </span>
            <span className="eyebrow">Margin &amp; Collateral Intelligence</span>
          </div>

          <h1
            className="serif m-0 leading-tight"
            style={{ fontSize: 30, fontWeight: 700, maxWidth: "22ch" }}
          >
            Choose the desk you are working from.
          </h1>

          <p
            className="m-0 text-[13px] leading-relaxed"
            style={{ color: "var(--ink-mid)", maxWidth: "76ch" }}
          >
            AETHER separates the three jobs a collateral call passes through: Legal
            interprets the Annex, Risk computes and signs off the transfer, and
            Audit reads the record without touching it. Your role decides which
            screens open and which actions are available.
          </p>

          <div className="flex flex-wrap items-center gap-2 mt-1">
            <Chip tone="warn" title="No password, no token, no identity provider.">
              Prototype access control
            </Chip>
            <Chip tone="warn">Simulated data</Chip>
            <span className="text-[11.5px]" style={{ color: "var(--ink-faint)" }}>
              This is not authentication. It demonstrates role separation, not
              identity.
            </span>
          </div>
        </header>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {ROLES.map((role) => {
            const profile = ROLE_PROFILES[role];
            const active = focused === role;
            return (
              <button
                key={role}
                onMouseEnter={() => setFocused(role)}
                onFocus={() => setFocused(role)}
                onClick={() => signIn(role)}
                className={`panel text-left flex flex-col gap-2.5 p-0 ${
                  active ? "panel-accent" : ""
                }`}
                style={{ alignItems: "stretch" }}
              >
                <span className="panel-head" style={{ display: "flex" }}>
                  <span className="panel-title">{role}</span>
                  {active && <Chip tone="accent">Enter →</Chip>}
                </span>

                <span className="px-3.5 pb-3.5 flex flex-col gap-2.5">
                  <span
                    className="text-[13px] font-semibold leading-snug"
                    style={{ color: "var(--ink)" }}
                  >
                    {profile.title}
                  </span>

                  <span
                    className="text-[11.5px] leading-snug"
                    style={{ color: "var(--ink-mid)", fontWeight: 400 }}
                  >
                    {profile.mandate}
                  </span>

                  <span className="flex flex-col gap-1 mt-0.5">
                    {(Object.keys(PERMISSION_LABELS) as Permission[])
                      .filter((permission) => can(role, permission))
                      .map((permission) => (
                        <span
                          key={permission}
                          className="flex items-start gap-1.5 text-[11px]"
                          style={{ color: "var(--ink-mute)", fontWeight: 400 }}
                        >
                          <span className="status-ok mono" aria-hidden="true">
                            ✓
                          </span>
                          {PERMISSION_LABELS[permission]}
                        </span>
                      ))}
                  </span>

                  <span
                    className="text-[11px] leading-snug pt-2 flex items-start gap-1.5"
                    style={{
                      borderTop: "1px solid var(--rule)",
                      color: "var(--warn)",
                      fontWeight: 400,
                    }}
                  >
                    <span className="mono" aria-hidden="true">
                      ✕
                    </span>
                    {profile.cannot}
                  </span>

                  <span
                    className="mono text-[10px]"
                    style={{ color: "var(--ink-faint)", fontWeight: 400 }}
                  >
                    {profile.identity}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        <p
          className="m-0 text-[11.5px] leading-relaxed"
          style={{ color: "var(--ink-faint)", maxWidth: "92ch" }}
        >
          Whichever role you choose is recorded as the actor on every action you
          take, and appears in the audit trail. Approval is additionally enforced
          server-side: the API refuses a sign-off from LEGAL or AUDITOR regardless
          of what this interface sends.
        </p>
      </div>
    </div>
  );
}

/**
 * The gate.
 *
 * Renders sign-in until a role is chosen. Hydration matters here: the role is
 * restored from session storage, which the server cannot see, so the first paint
 * must not assert either state. It renders nothing until the store has rehydrated.
 */
export function Gate({ children }: { children: React.ReactNode }) {
  const role = useAether((s) => s.role);

  // Subscribed to directly rather than announced from an effect: the server
  // snapshot is `false`, the client snapshot is whatever the persist middleware
  // has actually done, and React reconciles the two without a cascading render.
  const ready = useSyncExternalStore(
    (onChange) => useAether.persist.onFinishHydration(onChange),
    () => useAether.persist.hasHydrated(),
    () => false,
  );

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <span className="pulse mono text-[12px]" style={{ color: "var(--accent)" }}>
          ●
        </span>
      </div>
    );
  }

  return role ? <>{children}</> : <SignIn />;
}
