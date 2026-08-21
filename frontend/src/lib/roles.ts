/**
 * Roles and what each may do.
 *
 * .. rubric:: What this is, and what it is not
 *
 * This is **prototype access control**, not authentication. There is no password,
 * no token, no server-side session and no identity provider. What it demonstrates
 * is separation of duties: that a collateral platform must not let the same person
 * interpret the contract, compute the margin and sign off the transfer, and that
 * an auditor must be able to read everything and change nothing.
 *
 * The one permission that is enforced beyond the UI is approval. The API refuses a
 * sign-off from LEGAL or AUDITOR regardless of what the browser sends, because a
 * gate that exists only as a disabled button is not a gate.
 */

export const ROLES = ["RISK", "LEGAL", "ADMIN", "AUDITOR"] as const;

export type Role = (typeof ROLES)[number];

export type Permission =
  /** See exposure, margin, optimisation and the decision. */
  | "view:desk"
  /** See the CSA extraction, citations and confidence. */
  | "view:contract"
  /** Confirm a flagged clause and freeze the agreement. */
  | "act:review-contract"
  /** Sign off a margin decision. Also enforced server-side. */
  | "act:approve"
  /** Upload ledgers and run a reconciliation. */
  | "act:reconcile"
  /** Read the audit trail. */
  | "view:audit"
  /** Export the audit trail. */
  | "act:export-audit"
  /** See the workflow status board and system state. */
  | "view:admin";

export interface RoleProfile {
  role: Role;
  title: string;
  /** What this person is accountable for, in one line. */
  mandate: string;
  /** A plausible desk identity. Used as the recorded actor on any action. */
  identity: string;
  permissions: readonly Permission[];
  /** Stated plainly on the sign-in screen, so the separation is the point. */
  cannot: string;
}

export const ROLE_PROFILES: Record<Role, RoleProfile> = {
  RISK: {
    role: "RISK",
    title: "Risk & Collateral Management",
    mandate:
      "Runs the margin calculation, reviews the optimiser's allocation and signs " +
      "off the transfer.",
    identity: "j.mehta@aether.example",
    permissions: [
      "view:desk",
      "view:contract",
      "act:approve",
      "act:reconcile",
      "view:audit",
      "act:export-audit",
    ],
    cannot: "Cannot alter the extracted CSA terms — that is Legal's decision.",
  },
  LEGAL: {
    role: "LEGAL",
    title: "Legal & Documentation",
    mandate:
      "Reviews what the Legal-Clause Agent extracted, confirms or corrects flagged " +
      "terms against the Annex, and freezes the agreement.",
    identity: "r.oyelaran@aether.example",
    permissions: ["view:desk", "view:contract", "act:review-contract", "view:audit"],
    cannot:
      "Cannot approve a margin transfer. Interpreting the contract and signing off " +
      "the money it produces are different jobs.",
  },
  ADMIN: {
    role: "ADMIN",
    title: "Platform Operations",
    mandate:
      "Watches the workflow across the desk, holds system state, and has full " +
      "audit access.",
    identity: "ops.admin@aether.example",
    permissions: [
      "view:desk",
      "view:contract",
      "act:approve",
      "act:reconcile",
      "view:audit",
      "act:export-audit",
      "view:admin",
    ],
    cannot:
      "Cannot edit an audit record. The chain is append-only and no UI path writes " +
      "into it.",
  },
  AUDITOR: {
    role: "AUDITOR",
    title: "Internal Audit",
    mandate:
      "Reads the decision history and verifies the hash chain. Changes nothing.",
    identity: "audit.review@aether.example",
    permissions: ["view:desk", "view:contract", "view:audit", "act:export-audit"],
    cannot:
      "Cannot approve, reconcile, or alter a single term. Read-only by construction.",
  },
};

export function can(role: Role | null, permission: Permission): boolean {
  if (!role) return false;
  return ROLE_PROFILES[role].permissions.includes(permission);
}

/** Every action a role may take, for the "what you can do" panel on sign-in. */
export function permissionsOf(role: Role): readonly Permission[] {
  return ROLE_PROFILES[role].permissions;
}

export const PERMISSION_LABELS: Record<Permission, string> = {
  "view:desk": "View exposure, margin and optimisation",
  "view:contract": "View the CSA extraction and citations",
  "act:review-contract": "Confirm clauses and freeze the agreement",
  "act:approve": "Approve a margin decision",
  "act:reconcile": "Run a collateral reconciliation",
  "view:audit": "Read the audit trail",
  "act:export-audit": "Export the audit trail",
  "view:admin": "View the workflow status board",
};
