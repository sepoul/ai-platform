import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Top-level wrapper for a route's content. Centers, sets a sensible
 * max-width, and applies vertical rhythm. Replaces the deprecated
 * `.page-container` global class.
 */
export function PageContainer({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-8 sm:px-6 lg:px-8",
        className
      )}
    >
      {children}
    </div>
  );
}
