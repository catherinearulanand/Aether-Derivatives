/**
 * Session state — the one place the app remembers who is signed in and which two
 * snapshots are being compared.
 *
 * .. rubric:: Why this exists
 *
 * Before this store, every screen held its own ``useState("stress")``. Two tabs
 * could therefore show two different scenarios while both claimed to be "the"
 * collateral requirement. On a system whose entire argument is that one number is
 * traceable end to end, that is not a cosmetic defect.
 *
 * So scenario selection lives here, and every screen reads it. The **figures**
 * themselves are not stored here: they stay in the React Query cache, keyed by
 * scenario, fetched from the API and never copied, transformed or re-derived. This
 * store holds selection; the server holds truth.
 */

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { Role } from "./roles";
import { ROLE_PROFILES } from "./roles";

export interface Session {
  role: Role | null;
  /** The signed-in identity, recorded as the actor on any action taken. */
  identity: string | null;
  signedInAt: string | null;
}

interface AetherState extends Session {
  /** The snapshot the comparison treats as "before". */
  baselineKey: string;
  /** The snapshot under examination. Every screen renders this run. */
  currentKey: string;

  signIn: (role: Role) => void;
  signOut: () => void;
  setCurrent: (key: string) => void;
  setBaseline: (key: string) => void;
}

export const useAether = create<AetherState>()(
  persist(
    (set) => ({
      role: null,
      identity: null,
      signedInAt: null,

      // The quiet market is the baseline and the rate shock is the event. That
      // pairing is the demo's spine: it is the one comparison in which every
      // stage of the pipeline visibly moves.
      baselineKey: "base",
      currentKey: "stress",

      signIn: (role) =>
        set({
          role,
          identity: ROLE_PROFILES[role].identity,
          signedInAt: new Date().toISOString(),
        }),

      signOut: () => set({ role: null, identity: null, signedInAt: null }),

      setCurrent: (key) =>
        set((state) =>
          // Comparing a snapshot with itself reports twelve zeroes and teaches
          // nothing, so selecting the current baseline as the current scenario
          // steps the baseline out of the way.
          key === state.baselineKey
            ? { currentKey: key, baselineKey: state.currentKey }
            : { currentKey: key },
        ),

      setBaseline: (key) =>
        set((state) =>
          key === state.currentKey
            ? { baselineKey: key, currentKey: state.baselineKey }
            : { baselineKey: key },
        ),
    }),
    {
      name: "aether.session",
      // Session storage, not local: a prototype sign-in that survives closing the
      // browser would overstate what this is.
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        role: state.role,
        identity: state.identity,
        signedInAt: state.signedInAt,
        baselineKey: state.baselineKey,
        currentKey: state.currentKey,
      }),
    },
  ),
);
