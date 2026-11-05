import { ReportPanel } from "@/components/report-panel";
export default async function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  return <ReportPanel id={(await params).id} />;
}
