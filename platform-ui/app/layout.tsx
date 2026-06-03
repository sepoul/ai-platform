import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "ai-platform · admin",
  description:
    "Catalog browser + run inspector for the ai-platform control plane.",
};

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/job-definitions", label: "Job Definitions" },
  { href: "/artifact-types", label: "Artifact Types" },
  { href: "/code-packages", label: "Code Packages" },
];

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="border-b border-[var(--border)] bg-[var(--background)]">
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-6 py-3">
            <Link href="/" className="font-semibold">
              ai-platform <span className="text-[var(--muted-foreground)] font-normal">· admin</span>
            </Link>
            <nav className="flex items-center gap-1 text-sm">
              {NAV.slice(1).map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded px-3 py-1.5 hover:bg-[var(--muted)]"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
