"use client";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Latex } from "@/components/library";

interface ConversationBubbleProps {
  /** The turn shape works for both live (from CrewChatEvent.message) and
   * persisted (from MathConversationArtifact.turns). The shapes overlap
   * on the fields we render. */
  turn: {
    turn_index: number;
    agent_role: string;
    agent_persona?: string | null;
    display_name?: string | null;
    content: string;
    latex?: string | null;
    cost_usd?: number | null;
  };
}

/**
 * One agent move rendered as a chat bubble. Persona display_name (with
 * the emoji prefix from the persona front-matter) heads the bubble; the
 * content is rendered through `<Latex>` so inline `\(...\)` /
 * `\[...\]` segments compile via KaTeX. An optional `latex` field
 * (separate from inline math in `content`) renders as a block below.
 */
export function ConversationBubble({ turn }: ConversationBubbleProps) {
  const heading = turn.display_name || turn.agent_role;
  const persona = turn.agent_persona && turn.agent_persona !== turn.agent_role
    ? turn.agent_persona
    : null;

  return (
    <Card>
      <CardContent className="space-y-3 pt-4">
        <div className="flex items-center justify-between gap-3 text-sm">
          <div className="flex items-center gap-2 font-medium text-card-foreground">
            <span>{heading}</span>
            {persona && (
              <span className="font-normal text-xs text-muted-foreground">
                ({persona})
              </span>
            )}
            <Badge variant="secondary" className="font-mono text-[10px]">
              #{turn.turn_index + 1}
            </Badge>
          </div>
          {typeof turn.cost_usd === "number" && turn.cost_usd > 0 && (
            <span className="text-xs text-muted-foreground tabular-nums">
              ${turn.cost_usd.toFixed(4)}
            </span>
          )}
        </div>
        <Latex className="text-sm leading-relaxed">{turn.content}</Latex>
        {turn.latex && (
          <div className="rounded-md border border-border bg-muted/40 px-3 py-2">
            <Latex className="text-sm">{`\\[${turn.latex}\\]`}</Latex>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
