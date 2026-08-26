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

/**
 * The scenarios in the order their snapshots are dated.
 *
 * ``GET /api/v1/comparison/{before}/{after}`` returns 422 when ``before`` is dated
 * after ``after`` — a before/after comparison has to run forwards in time. Selection
 * therefore has to preserve this ordering. Swapping the pair, which is what this
 * store used to do when the two collided, produces a valid-looking selection that
 * the API rejects: choosing the quiet market as the current snapshot moved the rate
 * shock into the baseline and asked for 17 August → 14 August.
 */
const CHRONOLOGY = ["base", "stress", "crash"] as const;

const position = (key: string): number => (CHRONOLOGY as readonly string[]).indexOf(key);

/**
 * A baseline that is strictly earlier than ``current``.
 *
 * Keeps the caller's preference when it already is. Otherwise steps back one
 * snapshot — and when ``current`` is the earliest there is, returns ``current``
 * itself, which makes the pair identical and leaves the comparison panel in its
 * "choose a different baseline" state rather than in an error.
 */
function earlierThan(current: string, preferred: string): string {
  const c = position(current);
  const p = position(preferred);
  if (c < 0 || p < 0) return preferred;
  if (p < c) return preferred;
  return c > 0 ? CHRONOLOGY[c - 1] : current;
}

/** The mirror of {@link earlierThan}: a current snapshot strictly later than the baseline. */
function laterThan(baseline: string, preferred: string): string {
  const b = position(baseline);
  const p = position(preferred);
  if (b < 0 || p < 0) return preferred;
  if (p > b) return preferred;
  return b < CHRONOLOGY.length - 1 ? CHRONOLOGY[b + 1] : baseline;
}

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

      // Comparing a snapshot with itself reports twelve zeroes and teaches
      // nothing, so a collision moves the other selection out of the way — but
      // backwards in time, never forwards, so the pair stays one the comparison
      // endpoint will accept.
      setCurrent: (key) =>
        set((state) => ({
          currentKey: key,
          baselineKey: earlierThan(key, state.baselineKey),
        })),

      setBaseline: (key) =>
        set((state) => ({
          baselineKey: key,
          currentKey: laterThan(key, state.currentKey),
        })),
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
      // A session stored before the ordering rule existed can hold a pair that runs
      // backwards, and rehydrating it would reproduce the 422 on the next load. The
      // pair is therefore repaired on the way in rather than only on selection.
      merge: (persisted, current) => {
        const merged = { ...current, ...(persisted as Partial<AetherState>) };
        return {
          ...merged,
          baselineKey: earlierThan(merged.currentKey, merged.baselineKey),
        };
      },
    },
  ),
);
