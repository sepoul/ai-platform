/**
 * Math QA domain types — artifact + result shapes specific to the
 * `math_qa` job. Derived from the OpenAPI schema; consumers should
 * import from `@/lib/domains/math-qa` rather than reaching into the
 * platform schema directly.
 */
import type { components } from "@aiplatform/sdk";

type S = components["schemas"];

type Required_<T, K extends keyof T> = Omit<T, K> & {
  [P in K]-?: NonNullable<T[P]>;
};

export type MathQuestionArtifact = Required_<
  S["MathQuestionArtifact"],
  "artifact_id" | "created_at" | "created_by_job"
>;

export type GeneratedAnswerArtifact = Required_<
  S["GeneratedAnswerArtifact"],
  "artifact_id" | "created_at" | "created_by_job" | "reasoning_steps"
>;

export type UserCommentArtifact = Required_<
  S["UserCommentArtifact"],
  "artifact_id" | "created_at" | "created_by_job"
>;

export type LatexAnswerArtifact = Required_<
  S["LatexAnswerArtifact"],
  "artifact_id" | "created_at" | "created_by_job" | "is_valid" | "validation_attempts"
>;

export type FigureArtifact = Required_<
  S["FigureArtifact"],
  "artifact_id" | "created_at" | "created_by_job" | "validation_attempts"
>;

export type MathQAResult = Required_<
  S["MathQAResult"],
  "artifact_refs" | "question" | "ai_response" | "latex" | "figure" | "review"
> & {
  question: MathQuestionArtifact | null;
  ai_response: GeneratedAnswerArtifact | null;
  latex: LatexAnswerArtifact | null;
  figure: FigureArtifact | null;
  review: UserCommentArtifact | null;
};
