import { InterviewRecords } from "@/components/interview-records";
import { demoMode } from "@/lib/server-config";

export const dynamic = "force-dynamic";

export default async function InterviewRecordsPage() {
  return <InterviewRecords demo={await demoMode()} />;
}
