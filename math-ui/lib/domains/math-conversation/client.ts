import { jobsClient } from "@/lib/platform";
import type { RunSubmitResponse } from "@/lib/platform";

/**
 * Math Conversation domain client — typed submit shortcuts for the
 * `math_conversation` workflow. Two entry shapes (enforced by the
 * backend's `exactly_one_source` validator):
 *
 *   - `question_text` — fresh question, no prior single-shot answer.
 *   - `source_job_id` — refine a completed `math_qa` job; the panel
 *     hydrates that job's artifacts into its seed context.
 *
 * All other lifecycle calls (status / result) go through `jobsClient`.
 */
export const conversationClient = {
  submitFromQuestion(questionText: string, maxTurns?: number): Promise<RunSubmitResponse> {
    return jobsClient.submit({
      job_type: "math_conversation",
      question_text: questionText,
      max_turns: maxTurns ?? 12,
    });
  },

  submitFromSourceJob(sourceJobId: string, maxTurns?: number): Promise<RunSubmitResponse> {
    return jobsClient.submit({
      job_type: "math_conversation",
      source_job_id: sourceJobId,
      max_turns: maxTurns ?? 12,
    });
  },
};
