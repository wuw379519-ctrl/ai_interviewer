import { FormalInterviewSetup } from "@/components/formal-interview-setup";
import { demoMode } from "@/lib/server-config";

export const dynamic = "force-dynamic";

export default async function FormalInterviewPage() {
  return <FormalInterviewSetup demo={await demoMode()} />;
}
