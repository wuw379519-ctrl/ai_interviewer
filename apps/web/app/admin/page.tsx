import { demoMode } from "@/lib/server-config";
import { GovernancePanel } from "@/components/governance-panel";
export const dynamic = "force-dynamic";
export default async function AdminPage() { return <GovernancePanel demo={await demoMode()} />; }
