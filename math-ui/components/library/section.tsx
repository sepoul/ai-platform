import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Optional intra-page section wrapper with a small header. For pages
 * with multiple logical groups (e.g. workflow detail's params / graph /
 * stages). If you only need a heading without a bordered container,
 * compose `<h2>` + body directly.
 */
export function Section({
  title,
  description,
  actions,
  children,
  className,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("flex flex-col gap-3", className)}>
      {(title || actions) && (
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            {title && (
              <h2 className="text-sm font-semibold tracking-tight text-foreground">
                {title}
              </h2>
            )}
            {description && (
              <p className="text-xs text-muted-foreground">{description}</p>
            )}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}
