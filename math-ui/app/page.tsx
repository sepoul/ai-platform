"use client";

import { useRouter } from "next/navigation";
import { QuestionForm } from "@/components/math/question-form";
import { registerActiveJob } from "@/lib/platform";
import { PageContainer, PageHeader } from "@/components/library";

export default function Home() {
  const router = useRouter();

  const handleJobStarted = (jobId: string) => {
    registerActiveJob({ jobId, jobType: "math_qa", entityId: jobId, status: "running" });
    router.push(`/math-qa/${jobId}`);
  };

  return (
    <PageContainer>
      <PageHeader
        title="Math AI"
        subtitle="Ask any math question and get a step-by-step AI answer. Review the solution and leave your feedback."
      />
      <div className="max-w-2xl">
        <QuestionForm onJobStarted={handleJobStarted} />
      </div>
    </PageContainer>
  );
}
