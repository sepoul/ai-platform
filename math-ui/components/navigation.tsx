"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Boxes,
  Calculator,
  FileType2,
  History,
  Home,
  Shapes,
  Sigma,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  match: (pathname: string) => boolean;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Home", icon: Home, match: (p) => p === "/" },
  {
    href: "/math-qa",
    label: "Math Q&A",
    icon: Calculator,
    match: (p) => p.startsWith("/math-qa"),
  },
  {
    href: "/workflows",
    label: "Workflows",
    icon: Workflow,
    match: (p) => p.startsWith("/workflows"),
  },
  {
    href: "/jobs",
    label: "Jobs",
    icon: History,
    match: (p) => p.startsWith("/jobs"),
  },
  {
    href: "/artifacts",
    label: "Artifacts",
    icon: Boxes,
    match: (p) => p.startsWith("/artifacts"),
  },
  {
    href: "/artifact-types",
    label: "Artifact types",
    icon: FileType2,
    match: (p) => p.startsWith("/artifact-types"),
  },
  {
    href: "/latex",
    label: "LaTeX scratch",
    icon: Sigma,
    match: (p) => p.startsWith("/latex"),
  },
  {
    href: "/figures",
    label: "Figure scratch",
    icon: Shapes,
    match: (p) => p.startsWith("/figures"),
  },
];

export function Navigation() {
  const pathname = usePathname();

  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-60 flex-col border-r bg-sidebar">
      <div className="flex h-14 items-center gap-2.5 border-b px-5">
        <Link
          href="/"
          className="flex items-center gap-2 text-sidebar-foreground transition-colors hover:text-primary"
        >
          <div className="flex size-7 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Calculator className="size-4" />
          </div>
          <span className="text-sm font-semibold tracking-tight">Math AI</span>
        </Link>
      </div>

      <nav className="flex-1 overflow-y-auto p-3">
        <ul className="flex flex-col gap-0.5">
          {NAV_ITEMS.map((item) => {
            const active = item.match(pathname);
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-medium transition-colors",
                    active
                      ? "bg-sidebar-accent text-sidebar-accent-foreground"
                      : "text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
                  )}
                >
                  <Icon
                    className={cn(
                      "size-4 shrink-0",
                      active ? "text-primary" : "text-sidebar-foreground/60"
                    )}
                  />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="border-t px-5 py-3 text-[11px] text-sidebar-foreground/50">
        Platform · v0.1
      </div>
    </aside>
  );
}
