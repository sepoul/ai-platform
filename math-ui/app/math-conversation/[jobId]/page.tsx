"use client";

import { use, useEffect } from "react";
import { PageContainer, PageHeader } from "@/components/library";
import { useJobPolling, TERMINAL_JOB_STATUSES, clearActiveJob, updateActiveJob } from "@/lib/platform";
import type { JobStatus } from "@/lib/platform";
import { ConversationView } from "@/components/conversation/conversation-view";

interface Props {
  params: Promise<{ jobId: string }>;
}

export default function MathConversationJobPage({ params }: Props) {
  const { jobId } = use(params);
  const { status } = useJobPolling(jobId);

  // Sync the active-jobs rail so the global UI knows this conversation
  // is running / done. The rail clears on terminal states.
  useEffect(() => {
    if (!status) return;
    if (TERMINAL_JOB_STATUSES.includes(status as JobStatus)) {
      clearActiveJob("math_conversation", jobId);
    } else {
      updateActiveJob("math_conversation", jobId, { status: "running" });
    }
  }, [jobId, status]);

  return (
    <PageContainer>
      <PageHeader
        title="Math Conversation"
        subtitle={<span className="font-mono text-xs">{jobId}</span>}
      />
      <div className="flex max-w-3xl flex-col">
        <ConversationView jobId={jobId} />
      </div>
    </PageContainer>
  );
}
