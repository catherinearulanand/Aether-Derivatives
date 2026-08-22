"use client";

import { useAether } from "@/lib/store";
import { useSyncExternalStore } from "react";

/**
 * The AETHER landing page.
 *
 * One statement of what the platform does, and one way in. Every screen behind
 * this point is unchanged.
 *
 * .. rubric:: Why entry is ADMIN
 *
 * Permissions still gate `/admin`, `/reconciliation`, `/audit` and `/review`,
 * and still decide what the nav shows and whether a decision can be approved.
 * ADMIN is the role holding all eight permissions, so entering as ADMIN is what
 * makes every page reachable and leaves nothing hidden. The role machinery in
 * `lib/roles.ts` is untouched; only the way a role is chosen has changed.
 */
export function SignIn() {
  const signIn = useAether((s) => s.signIn);

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div
        className="flex flex-col items-center text-center"
        style={{ maxWidth: 640 }}
      >
        <h1
          className="serif m-0"
          style={{
            fontSize: "clamp(2.9rem, 9vw, 4.6rem)",
            fontWeight: 300,
            letterSpacing: "0.34em",
            lineHeight: 1,
            textIndent: "0.34em",
          }}
        >
          AETHER
        </h1>

        <div
          style={{
            width: 56,
            height: 1,
            background: "var(--accent)",
            opacity: 0.55,
            margin: "28px 0",
          }}
        />

        <p
          className="m-0"
          style={{
            fontSize: "1.02rem",
            fontWeight: 300,
            lineHeight: 1.65,
            color: "var(--ink-mid)",
            maxWidth: "44ch",
          }}
        >
          Unified intelligence for derivatives, risk and collateral management.
        </p>

        <button
          className="primary"
          onClick={() => signIn("ADMIN")}
          style={{
            marginTop: 40,
            padding: "13px 38px",
            borderRadius: 999,
            fontSize: "0.78rem",
            fontWeight: 600,
            letterSpacing: "0.2em",
            textTransform: "uppercase",
          }}
        >
          Enter AETHER
        </button>

        <p
          className="m-0"
          style={{
            marginTop: 44,
            fontSize: "0.7rem",
            letterSpacing: "0.13em",
            textTransform: "uppercase",
            color: "var(--ink-faint)",
          }}
        >
          Prototype · Simulated data
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
