import { Workspace } from "@/components/workspace";
import { demoMode } from "@/lib/server-config";
export const dynamic = "force-dynamic";
export default async function HomePage() { return <Workspace demo={await demoMode()} />; }
