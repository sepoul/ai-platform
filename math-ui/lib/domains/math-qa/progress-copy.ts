export type JobProgressKind = "math_qa";

export interface ResolvedJobProgressCopy {
  whatsHappening: string;
  whyItMatters: string;
}

export function formatStageLabel(stage: string | null): string | null {
  if (!stage?.trim()) return null;
  return stage.trim().replace(/_/g, " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export function resolveJobProgressRichCopy(
  _kind: JobProgressKind,
  input: { stage: string | null; message: string; waitingFor?: string | null }
): ResolvedJobProgressCopy {
  const h = `${input.stage ?? ""} ${input.message ?? ""} ${input.waitingFor ?? ""}`.toLowerCase();

  if (h.includes("receive") || h.includes("question")) {
    return {
      whatsHappening: "Parsing and storing your math question.",
      whyItMatters: "The question is validated and queued for the AI solver.",
    };
  }
  if (h.includes("ai") || h.includes("answer") || h.includes("generat")) {
    return {
      whatsHappening: "The AI is working through your question step by step.",
      whyItMatters: "Each reasoning step is recorded so you can follow the solution.",
    };
  }
  if (h.includes("review") || h.includes("waiting") || h.includes("comment") || h.includes("human")) {
    return {
      whatsHappening: "The AI has answered — your review is needed.",
      whyItMatters: "Your rating and feedback help improve future answers.",
    };
  }

  return {
    whatsHappening: "Running the math Q&A pipeline.",
    whyItMatters: "The AI will solve your question and ask for your feedback when done.",
  };
}
