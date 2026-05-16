import type { ReactNode } from "react";
import { AlertCircle, Inbox } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Async-state placeholders. Pages should pick the variant that matches
 * the current state instead of assembling their own card.
 */

export function LoadingCard({
  rows = 3,
  className,
}: {
  rows?: number;
  className?: string;
}) {
  return (
    <Card className={className}>
      <CardContent className="flex flex-col gap-2.5 p-4">
        {Array.from({ length: rows }).map((_, i) => (
          <Skeleton
            key={i}
            className="h-4"
            style={{ width: `${90 - i * 12}%` }}
          />
        ))}
      </CardContent>
    </Card>
  );
}

export function ErrorCard({
  title = "Something went wrong",
  children,
}: {
  title?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Alert variant="destructive">
      <AlertCircle />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  );
}

export function EmptyCard({
  icon = <Inbox className="size-5 text-muted-foreground" />,
  children,
}: {
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardContent className="flex items-center gap-3 p-6">
        <div className="flex size-9 items-center justify-center rounded-md bg-muted">
          {icon}
        </div>
        <div className="text-sm text-muted-foreground">{children}</div>
      </CardContent>
    </Card>
  );
}
