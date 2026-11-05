import { apiErrorSchema } from "@aii/core";

/** No client text is sent: the backend selects the authenticated current question. */
export async function questionAudio(id: string, token: string, questionSeq: number, turnSeq: number, signal: AbortSignal): Promise<Blob> {
  const query = new URLSearchParams({ questionSeq: String(questionSeq), turnSeq: String(turnSeq) });
  const response = await fetch(`/api/interviews/${id}/tts?${query}`, {
    headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal,
  });
  if (!response.ok) {
    const raw: unknown = await response.json();
    throw new Error(apiErrorSchema.safeParse(raw).data?.error.message ?? "题目播报不可用，请阅读文字题目。");
  }
  if (response.headers.get("content-type")?.split(";")[0] !== "audio/mpeg") throw new Error("播报格式无效，请阅读文字题目。");
  const audio = await response.blob();
  if (!audio.size || audio.size > 2 * 1024 * 1024) throw new Error("播报内容无效，请阅读文字题目。");
  return audio;
}
