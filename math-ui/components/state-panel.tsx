import Link from "next/link";
import { Card, CardContent } from "@/components/ui/card";
import { buttonVariants } from "@/components/ui/button";

type StatePanelVariant = "info" | "error" | "success" | "warning";

const variantStyles: Record<StatePanelVariant, string> = {
  info: "border-[var(--color-info)]/30 bg-[var(--color-info)]/10 text-[var(--color-info)]",
  error: "border-[var(--color-error)]/30 bg-[var(--color-error)]/10 text-[var(--color-error)]",
  success:
    "border-[var(--color-success)]/30 bg-[var(--color-success)]/10 text-[var(--color-success)]",
  warning:
    "border-[var(--color-warning)]/30 bg-[var(--color-warning)]/10 text-[var(--color-warning)]",
};

interface StatePanelProps {
  variant?: StatePanelVariant;
  title?: string;
  message: string;
  actionLabel?: string;
  actionHref?: string;
}

export function StatePanel({
  variant = "info",
  title,
  message,
  actionLabel,
  actionHref,
}: StatePanelProps) {
  return (
    <Card className={variantStyles[variant]}>
      <CardContent className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            {title && <p className="font-medium">{title}</p>}
            <p className={title ? "mt-1" : ""}>{message}</p>
          </div>
          {actionLabel && actionHref && (
            <Link
              href={actionHref}
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              {actionLabel}
            </Link>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
