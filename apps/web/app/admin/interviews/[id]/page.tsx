import { InterviewRecords } from "@/components/interview-records";
import { demoMode } from "@/lib/server-config";

export const dynamic = "force-dynamic";

export default async function InterviewRecordPage({ params }: { params: Promise<{ id: string }> }) {
  return <InterviewRecords demo={await demoMode()} id={(await params).id} />;
}
