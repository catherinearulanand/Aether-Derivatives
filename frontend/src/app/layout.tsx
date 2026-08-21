import type { Metadata } from "next";
import "./globals.css";
import { Assistant } from "@/components/Assistant";
import { Providers } from "@/components/Providers";
import { Shell } from "@/components/Shell";
import { Gate } from "@/components/SignIn";

export const metadata: Metadata = {
  title: "AETHER — Margin & Collateral Intelligence",
  description:
    "Prototype. AI-extracted CSA terms, deterministically calculated margin, " +
    "optimised collateral. All data simulated.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Providers>
          {/* The gate wraps everything: no screen renders before a role is chosen,
              so no panel has to reason about a null role. The assistant sits
              inside it for the same reason — it answers about the signed-in
              role's permissions and has none to check when nobody is signed in. */}
          <Gate>
            <Shell>{children}</Shell>
            <Assistant />
          </Gate>
        </Providers>
      </body>
    </html>
  );
}
