"use client";

import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, Loader2, AlertTriangle } from "lucide-react";
import {
  formatStageLabel,
  resolveJobProgressRichCopy,
  type JobProgressKind,
} from "@/lib/domains/math-qa";

export interface RichJobProgressProps {
  kind: JobProgressKind;
  inProgressTitle: string;
  failedTitle: string;
  status: string | null;
  stage: string | null;
  message: string;
  error: string | null;
  waitingFor?: string | null;
  onRetry?: () => void;
  stepper?: ReactNode;
  processOverview?: ReactNode;
}

export function RichJobProgress({
  kind,
  inProgressTitle,
  failedTitle,
  status,
  stage,
  message,
  error,
  waitingFor,
  onRetry,
  stepper,
  processOverview,
}: RichJobProgressProps) {
  const u = (status ?? "").toUpperCase();
  const isFailed = u === "FAILED" || u === "CANCELLED";
  const isComplete = u === "SUCCEEDED" || u === "SUCCESS";
  const copy = resolveJobProgressRichCopy(kind, {
    stage,
    message,
    waitingFor,
  });
  const stageLabel = formatStageLabel(stage);

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 pt-5">
        <div className="flex items-start gap-3">
          {!isFailed && !isComplete && (
            <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin text-primary" />
          )}
          {isComplete && (
            <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-[var(--color-success)]" />
          )}
          {isFailed && (
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
          )}
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-medium text-card-foreground">
              {isFailed
                ? failedTitle
                : isComplete
                  ? "Completed"
                  : inProgressTitle}
            </h3>
            {stageLabel && (
              <p className="mt-1 text-xs text-muted-foreground">
                <span className="font-medium text-card-foreground">Stage:</span>{" "}
                {stageLabel}
              </p>
            )}
            {waitingFor && !isFailed && (
              <Badge variant="outline" className="mt-1.5 text-[11px] font-mono">
                Waiting: {waitingFor}
              </Badge>
            )}
          </div>
        </div>

        {stepper != null && stepper !== false && (
          <div className="border-t border-border pt-4">{stepper}</div>
        )}

        <div className="space-y-3 rounded-lg border border-border bg-muted/40 p-4 text-sm">
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              What&apos;s happening
            </p>
            <p className="text-card-foreground">{copy.whatsHappening}</p>
          </div>
          <div>
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Why this matters
            </p>
            <p className="text-muted-foreground">{copy.whyItMatters}</p>
          </div>
        </div>

        {processOverview != null && processOverview !== false && (
          <div className="border-t border-border pt-4">{processOverview}</div>
        )}

        {message?.trim() && (
          <div className="rounded-lg border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
            <span className="font-medium text-card-foreground">Latest update: </span>
            {message}
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {isFailed && onRetry && (
          <Button variant="default" size="sm" className="self-start" onClick={onRetry}>
            Retry
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
