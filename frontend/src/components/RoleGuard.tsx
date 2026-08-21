"use client";

import { Chip, Panel } from "@/components/primitives";
import { PERMISSION_LABELS, ROLES, ROLE_PROFILES, can, type Permission } from "@/lib/roles";
import { useAether } from "@/lib/store";

/**
 * Page-level permission gate.
 *
 * A role that cannot reach a screen does not see it in the navigation, but a
 * bookmarked or typed URL must still be refused — and refused with a reason. A
 * blank page or a redirect teaches the reader nothing; this names the permission
 * required and which roles hold it, which is what someone in an operations team
 * actually needs to know.
 *
 * This is a UI boundary. The action that carries real consequence — approving a
 * margin decision — is refused by the API independently.
 */
export function RoleGuard({
  permission,
  children,
}: {
  permission: Permission;
  children: React.ReactNode;
}) {
  const role = useAether((s) => s.role);
  const signOut = useAether((s) => s.signOut);

  if (can(role, permission)) return <>{children}</>;

  const holders = ROLES.filter((candidate) => can(candidate, permission));

  return (
    <div className="p-4 max-w-[760px] mx-auto">
      <Panel
        title="Not available to your role"
        aside={<Chip tone="crit">{role}</Chip>}
      >
        <div className="px-4 py-4 flex flex-col gap-3.5">
          <p className="m-0 text-[13px] leading-relaxed" style={{ color: "var(--ink-mid)" }}>
            This screen requires{" "}
            <strong style={{ color: "var(--ink)" }}>
              {PERMISSION_LABELS[permission].toLowerCase()}
            </strong>
            . You are signed in as {role} — {ROLE_PROFILES[role!].title}.
          </p>

          <p className="m-0 text-[12.5px]" style={{ color: "var(--ink-mute)" }}>
            {ROLE_PROFILES[role!].cannot}
          </p>

          <div
            className="flex flex-wrap items-center gap-2 pt-3"
            style={{ borderTop: "1px solid var(--rule)" }}
          >
            <span className="eyebrow">Held by</span>
            {holders.map((holder) => (
              <Chip key={holder} tone="accent">
                {holder}
              </Chip>
            ))}
            <button className="ml-auto" onClick={signOut}>
              Switch role
            </button>
          </div>
        </div>
      </Panel>
    </div>
  );
}
