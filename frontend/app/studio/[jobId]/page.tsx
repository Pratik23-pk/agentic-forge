import { notFound } from "next/navigation";

import { BackendUnavailable } from "@/components/studio/backend-unavailable";
import { Studio } from "@/components/studio/studio";
import { BackendError, getJobChain } from "@/lib/backend/client";
import { conversationFromJobs, isLive } from "@/lib/gateway/translate";

export default async function ProjectPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;

  let chain;
  try {
    chain = await getJobChain(jobId);
  } catch (error) {
    if (error instanceof BackendError && error.status === 404) notFound();
    return <BackendUnavailable message={(error as Error).message} />;
  }

  const latest = chain.at(-1)!;
  return (
    <Studio
      chatId={jobId}
      initialMessages={conversationFromJobs(chain)}
      resume={isLive(latest)}
      initialProjectName={latest.request.project_id}
    />
  );
}
