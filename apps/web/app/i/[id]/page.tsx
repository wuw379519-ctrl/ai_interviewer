import { CandidateInterview } from "@/components/candidate-interview";
export default async function CandidatePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CandidateInterview id={id} />;
}
