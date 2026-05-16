import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/**
 * Vertical list of "labelled value" rows for spec-y data — workflow
 * params, artifact fields, etc.
 */

export interface FieldRow {
  name: string;
  badges?: ReactNode[];
  description?: ReactNode;
}

export function FieldList({
  rows,
  className,
}: {
  rows: FieldRow[];
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-2.5", className)}>
      {rows.map((row) => (
        <div
          key={row.name}
          className="flex flex-wrap items-baseline gap-2 text-sm"
        >
          <span className="font-mono font-medium text-foreground">
            {row.name}
          </span>
          {row.badges?.map((b, i) => (
            <span key={i} className="contents">
              {b}
            </span>
          ))}
          {row.description && (
            <span className="text-xs leading-relaxed text-muted-foreground">
              — {row.description}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

/**
 * Convenience badge shorthand for FieldList rows. Slightly tighter
 * than the default Badge variant=outline.
 */
export function FieldBadge({
  children,
  mono,
  variant = "outline",
}: {
  children: ReactNode;
  mono?: boolean;
  variant?: "outline" | "secondary";
}) {
  return (
    <Badge
      variant={variant}
      className={cn("text-[10.5px] font-medium", mono && "font-mono")}
    >
      {children}
    </Badge>
  );
}
