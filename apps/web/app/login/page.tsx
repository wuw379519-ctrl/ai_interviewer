import { AccountLoginPage } from "@/components/workspace-login";
import { demoMode } from "@/lib/server-config";

export const dynamic = "force-dynamic";

export default async function LoginPage() {
  return <AccountLoginPage demo={await demoMode()} />;
}
