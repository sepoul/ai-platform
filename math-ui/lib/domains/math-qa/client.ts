import { jobsClient } from "@/lib/platform";
import type { RunSubmitResponse } from "@/lib/platform";

/**
 * Math QA domain client — typed submit shortcut for the `math_qa`
 * workflow. All other lifecycle calls (status / result / review) are
 * platform-level via `jobsClient`.
 */
export const mathClient = {
  submitQuestion(questionText: string, topic?: string): Promise<RunSubmitResponse> {
    return jobsClient.submit({
      job_type: "math_qa",
      question_text: questionText,
      topic: topic ?? null,
      created_by: null,
    });
  },
};
