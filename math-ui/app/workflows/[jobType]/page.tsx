"use client";

import { use } from "react";
import { useWorkflowSpec } from "@/lib/platform";
import { WorkflowSpecView } from "@/components/workflow/workflow-spec-view";
import {
  ErrorCard,
  LoadingCard,
  PageContainer,
  PageHeader,
} from "@/components/library";

interface Props {
  params: Promise<{ jobType: string }>;
}

export default function WorkflowDetailPage({ params }: Props) {
  const { jobType } = use(params);
  const { spec, loading, error } = useWorkflowSpec(jobType);

  return (
    <PageContainer>
      <PageHeader
        title={<span className="font-mono">{jobType}</span>}
        subtitle="Static workflow spec — stages, edges, and submit parameters as declared by the platform."
      />

      {loading && <LoadingCard rows={6} />}
      {error && <ErrorCard>{error}</ErrorCard>}
      {spec && <WorkflowSpecView spec={spec} />}
    </PageContainer>
  );
}
