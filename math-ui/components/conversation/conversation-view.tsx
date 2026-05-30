"use client";

import { useEffect, useMemo, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useJobPolling, TERMINAL_JOB_STATUSES } from "@/lib/platform";
import { jobsClient } from "@/lib/platform";
import {
  useCrewChatStream,
  type CrewChatEvent,
  type MathConversationArtifact,
  type MathConversationResult,
  type ConversationTurn,
} from "@/lib/domains/math-conversation";
import { ConversationBubble } from "./conversation-bubble";

interface ConversationViewProps {
  jobId: string;
}

/**
 * Live + post-terminal renderer for a `math_conversation` job.
 *
 * Live path: subscribes to the SSE log stream, splits `CrewChatEvent`s
 * out of plain logs, and renders the roll-call + bubbles + typing
 * indicator + running status footer from the event sequence.
 *
 * Terminal path: once the job hits SUCCEEDED, fetches
 * `/jobs/{id}/result` and renders the persisted
 * `MathConversationArtifact` as the source of truth. The stream is
 * disabled at that point — the event log was just a live preview.
 *
 * If the result fetch fails (very long run, partial state), the view
 * falls back to whatever the event stream captured.
 */
export function ConversationView({ jobId }: ConversationViewProps) {
  const polling = useJobPolling(jobId);
  const status = polling.status;
  const pollError = polling.error;
  const isTerminal = status !== null && TERMINAL_JOB_STATUSES.includes(status);
  const isSucceeded = status === "SUCCEEDED";
  const isFailed = status === "FAILED" || status === "CANCELLED";

  const { events, connected } = useCrewChatStream(jobId, !isTerminal);
  const view = useMemo(() => deriveView(events), [events]);

  const [artifact, setArtifact] = useState<MathConversationArtifact | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  // Derived from artifact/error rather than a separate setState — avoids
  // the cascading-render pattern react-hooks/set-state-in-effect flags.
  const loadingArtifact = isSucceeded && artifact === null && artifactError === null;

  useEffect(() => {
    if (!isSucceeded) return;
    jobsClient
      .getResult(jobId)
      .then((res) => {
        const result = res.result as MathConversationResult | null;
        setArtifact(result?.conversation ?? null);
      })
      .catch((err: unknown) => {
        setArtifactError(err instanceof Error ? err.message : "Failed to load result");
      });
  }, [isSucceeded, jobId]);

  // Source-of-truth turns: persisted artifact wins once available; live
  // events fill in until then. Both shapes are typed `ConversationTurn[]`
  // but the schema-derived one carries optional `tool_calls`; coerce to
  // the tightened shape (`tool_calls` always present).
  const turns: ConversationTurn[] = (artifact?.turns ?? view.turns).map((t) => ({
    ...t,
    tool_calls: t.tool_calls ?? [],
    cost_usd: t.cost_usd ?? 0,
  }));

  return (
    <div className="flex flex-col gap-4">
      <StatusBanner
        status={status}
        connected={connected}
        pollError={pollError}
        artifactError={artifactError}
        loadingArtifact={loadingArtifact}
      />

      {view.rollCall.length > 0 && turns.length === 0 && (
        <Card>
          <CardContent className="space-y-2 pt-4 text-sm text-muted-foreground">
            <div>Panel assembling:</div>
            <div className="flex flex-wrap gap-2">
              {view.rollCall.map((m) => (
                <Badge key={m.role} variant="secondary">
                  {m.display}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {turns.map((turn, idx) => (
        <ConversationBubble
          key={`${turn.turn_index}-${turn.agent_role}-${idx}`}
          turn={enrichTurnDisplay(turn, view.displayByRole)}
        />
      ))}

      {!isTerminal && view.typing && (
        <p className="text-sm italic text-muted-foreground">
          {view.typing} is thinking…
        </p>
      )}

      {view.concluded && (
        <Card>
          <CardContent className="pt-4 text-sm">
            <span className="font-medium text-card-foreground">
              {view.concluded.display} called conclude:
            </span>{" "}
            <span className="text-muted-foreground">
              {view.concluded.reason || "(no reason given)"}
            </span>
          </CardContent>
        </Card>
      )}

      {(view.lastStatus || artifact) && (
        <StatusFooter
          turnsUsed={artifact ? artifact.turns.length : view.lastStatus?.turnsUsed}
          turnsBudget={view.lastStatus?.turnsBudget}
          costUsd={artifact ? artifact.total_cost_usd : view.lastStatus?.cost}
          stopReason={artifact?.stop_reason}
          isTerminal={isTerminal}
          isFailed={isFailed}
        />
      )}
    </div>
  );
}

interface DerivedView {
  /** Personae that have signed in but haven't spoken yet — used for the
   * "Panel assembling" pre-roll card. Clears once the first turn lands. */
  rollCall: { role: string; display: string }[];
  /** Persona name → display_name lookup so the persisted artifact (which
   * doesn't carry display_name on each turn) can reuse the live ones. */
  displayByRole: Record<string, string>;
  /** Turns rebuilt from `message` events for the live path. */
  turns: ConversationTurn[];
  /** "{display} is typing…" — set on `is_typing`, cleared on next message. */
  typing: string | null;
  /** Latest `status` event payload for the footer. */
  lastStatus: { turnsUsed: number; turnsBudget: number | null; cost: number } | null;
  /** Set when a `concluded` event arrives. */
  concluded: { display: string; reason: string } | null;
}

function deriveView(events: CrewChatEvent[]): DerivedView {
  const rollCall: { role: string; display: string }[] = [];
  const displayByRole: Record<string, string> = {};
  const turns: ConversationTurn[] = [];
  let typing: string | null = null;
  let lastStatus: DerivedView["lastStatus"] = null;
  let concluded: DerivedView["concluded"] = null;

  for (const ev of events) {
    if (ev.agent_role && ev.display_name) {
      displayByRole[ev.agent_role] = ev.display_name;
    }
    switch (ev.event) {
      case "signed_in":
        if (ev.agent_role && ev.display_name) {
          rollCall.push({ role: ev.agent_role, display: ev.display_name });
        }
        break;
      case "is_typing":
        typing = ev.display_name || ev.agent_role || null;
        break;
      case "message":
        typing = null;
        if (typeof ev.turn_index === "number" && ev.agent_role) {
          turns.push({
            turn_index: ev.turn_index,
            agent_role: ev.agent_role,
            agent_persona: ev.agent_role,
            content: ev.content ?? "",
            latex: ev.latex ?? null,
            figure: null,
            tool_calls: [],
            cost_usd: ev.cost_usd ?? 0,
          });
        }
        break;
      case "status":
        lastStatus = {
          turnsUsed: ev.turns_used ?? turns.length,
          turnsBudget: ev.turns_budget ?? null,
          cost: ev.cost_usd ?? 0,
        };
        break;
      case "concluded":
        concluded = {
          display: ev.display_name || ev.agent_role || "Panel",
          reason: ev.content || "",
        };
        break;
      case "signed_out":
      case "tool_call":
      case "tool_result":
        // No view state changes for these in v1; tool events are still
        // useful for debugging the log stream.
        break;
    }
  }

  return { rollCall, displayByRole, turns, typing, lastStatus, concluded };
}

function enrichTurnDisplay(
  turn: ConversationTurn,
  displayByRole: Record<string, string>,
): ConversationTurn & { display_name?: string | null } {
  return {
    ...turn,
    display_name: displayByRole[turn.agent_role] ?? null,
  };
}

interface StatusBannerProps {
  status: string | null;
  connected: boolean;
  pollError: string | null;
  artifactError: string | null;
  loadingArtifact: boolean;
}

function StatusBanner({
  status,
  connected,
  pollError,
  artifactError,
  loadingArtifact,
}: StatusBannerProps) {
  if (status === "FAILED" || status === "CANCELLED") {
    return (
      <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        Job {status.toLowerCase()}{pollError ? ` — ${pollError}` : ""}.
      </p>
    );
  }
  if (artifactError) {
    return (
      <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
        Loading transcript: {artifactError}
      </p>
    );
  }
  if (status === "SUCCEEDED" && loadingArtifact) {
    return (
      <p className="text-sm text-muted-foreground">Loading final transcript…</p>
    );
  }
  if (status === "PENDING") {
    return <p className="text-sm text-muted-foreground">Queued — waiting for a worker.</p>;
  }
  if (status === "RUNNING" && !connected) {
    return <p className="text-sm text-muted-foreground">Connecting to live log stream…</p>;
  }
  return null;
}

interface StatusFooterProps {
  turnsUsed?: number;
  turnsBudget?: number | null;
  costUsd?: number;
  stopReason?: string;
  isTerminal: boolean;
  isFailed: boolean;
}

function StatusFooter({
  turnsUsed,
  turnsBudget,
  costUsd,
  stopReason,
  isTerminal,
  isFailed,
}: StatusFooterProps) {
  const pieces: string[] = [];
  if (typeof turnsUsed === "number") {
    pieces.push(
      typeof turnsBudget === "number"
        ? `${turnsUsed} / ${turnsBudget} turns`
        : `${turnsUsed} turn${turnsUsed === 1 ? "" : "s"}`,
    );
  }
  if (typeof costUsd === "number") {
    pieces.push(`$${costUsd.toFixed(4)}`);
  }
  if (stopReason) {
    pieces.push(`stopped: ${stopReason}`);
  }
  return (
    <p className={`text-xs ${isFailed ? "text-destructive" : "text-muted-foreground"}`}>
      {pieces.join(" · ") || (isTerminal ? "Done." : "Running…")}
    </p>
  );
}
