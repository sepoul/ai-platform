"use client";

import { useRouter } from "next/navigation";
import { ConversationForm } from "@/components/conversation/conversation-form";
import { registerActiveJob } from "@/lib/platform";
import { PageContainer, PageHeader } from "@/components/library";

export default function MathConversationPage() {
  const router = useRouter();

  const handleJobStarted = (jobId: string) => {
    registerActiveJob({
      jobId,
      jobType: "math_conversation",
      entityId: jobId,
      status: "running",
    });
    router.push(`/math-conversation/${jobId}`);
  };

  return (
    <PageContainer>
      <PageHeader
        title="Math Conversation"
        subtitle="Run a panel of personae against a math question and watch them brainstorm turn by turn."
      />
      <div className="max-w-2xl">
        <ConversationForm onJobStarted={handleJobStarted} />
      </div>
    </PageContainer>
  );
}
