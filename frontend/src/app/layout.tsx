import type { Metadata } from "next";
import { Montserrat } from "next/font/google";
import "./globals.css";
import { Assistant } from "@/components/Assistant";
import { Providers } from "@/components/Providers";
import { Shell } from "@/components/Shell";
import { Gate } from "@/components/SignIn";

// Self-hosted by next/font, so there is no external request and no flash of
// fallback text. Exposed as a CSS variable and consumed through the existing
// --sans / --serif tokens, so no component needs a className change.
const montserrat = Montserrat({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-montserrat",
  display: "swap",
});

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
    <html lang="en" className={montserrat.variable}>
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
