/**
 * Math QA domain — typed shapes and clients specific to the `math_qa`
 * workflow. Built on top of `@/lib/platform`; the platform never
 * imports from this module.
 */
export type {
  MathQuestionArtifact,
  GeneratedAnswerArtifact,
  UserCommentArtifact,
  LatexAnswerArtifact,
  FigureArtifact,
  MathQAResult,
} from "./types";

export { mathClient } from "./client";

export {
  formatStageLabel,
  resolveJobProgressRichCopy,
  type JobProgressKind,
  type ResolvedJobProgressCopy,
} from "./progress-copy";
