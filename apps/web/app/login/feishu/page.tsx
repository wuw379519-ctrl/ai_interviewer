import { FeishuCallbackPanel } from "@/components/feishu-callback";

export const dynamic = "force-dynamic";

type Search = { code?: string; state?: string; error?: string };

export default async function FeishuLoginCallbackPage({
  searchParams,
}: {
  searchParams: Promise<Search> | Search;
}) {
  const params = await Promise.resolve(searchParams);
  return <FeishuCallbackPanel params={{
    code: typeof params.code === "string" ? params.code : undefined,
    state: typeof params.state === "string" ? params.state : undefined,
    error: typeof params.error === "string" ? params.error : undefined,
  }} />;
}
