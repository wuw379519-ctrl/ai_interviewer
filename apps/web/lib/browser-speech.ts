import { z } from "zod";
export interface LocalRecognitionResult { isFinal: boolean; 0: { transcript: string } }
export interface LocalRecognitionEvent { resultIndex: number; results: ArrayLike<LocalRecognitionResult> }
export interface LocalRecognition {
  processLocally: boolean; lang: string; continuous: boolean; interimResults: boolean;
  onresult: ((event: LocalRecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void; stop(): void; abort(): void;
}
export interface LocalRecognitionConstructor {
  new(): LocalRecognition;
  available?(options: { langs: string[]; processLocally: boolean }): Promise<string>;
  install?(options: { langs: string[]; processLocally: boolean }): Promise<boolean>;
}
export function recognitionConstructor(): LocalRecognitionConstructor | undefined {
  const browser = window as Window & { SpeechRecognition?: LocalRecognitionConstructor; webkitSpeechRecognition?: LocalRecognitionConstructor };
  return browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
}
export async function localRecognitionAvailability(Constructor: LocalRecognitionConstructor): Promise<string> {
  if (!Constructor.available) return "需实际启动验证";
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    const status: unknown = await Promise.race([Constructor.available({ langs: ["zh-CN"], processLocally: true }), new Promise<never>((_resolve, reject) => {
      timeout = setTimeout(() => reject(new Error("中文识别能力查询超时（5秒）。浏览器本地识别暂不可用，请使用文字或配置企业转写服务。")), 5000);
    })]);
    return z.enum(["available", "downloadable", "downloading", "unavailable"]).parse(status);
  } finally { if (timeout) clearTimeout(timeout); }
}
export async function createLocalRecognition(): Promise<LocalRecognition> {
  const Constructor = recognitionConstructor();
  if (!Constructor) throw new Error("此浏览器没有设备端语音识别，可使用企业转写服务或改用文字。");
  const recognition = new Constructor();
  if (!("processLocally" in recognition)) throw new Error("此浏览器不能保证本地识别，已阻止云端回退。请配置企业语音服务或改用文字。");
  recognition.processLocally = true; recognition.lang = "zh-CN"; recognition.continuous = true; recognition.interimResults = true;
  if (Constructor.available && await localRecognitionAvailability(Constructor) !== "available") {
    throw new Error("中文设备端语音包不可用，可尝试安装离线语音包、使用企业转写服务或改用文字。");
  }
  return recognition;
}
