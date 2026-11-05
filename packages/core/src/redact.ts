import { resumeProfileSchema, type ResumeProfile } from "./schemas";

/**
 * 打分前去标识化。
 *
 * 目的：评分只看「行为与结果」，不看「他是谁」。姓名、性别、年龄、院校、籍贯、婚育、健康
 * 这些信息与维度无关，却会稳定影响模型打分（已知偏见源），因此在进入打分 prompt 之前一律抹掉。
 *
 * 注意：去标识化只作用于**打分的输入副本**；原始 turns 仍按保留期保存（合规要求可追溯）。
 */

export interface RedactOptions {
  /** 候选人姓名（来自 candidates.full_name），按原样抹除。 */
  candidateName?: string | null;
  /** 其他需要抹除的已知实体（公司名可选保留，院校名默认抹除）。 */
  extraTerms?: readonly string[];
}

export interface RedactResult {
  readonly text: string;
  readonly redactions: number;
  readonly categories: readonly string[];
}

const PATTERNS: readonly { category: string; pattern: RegExp; replacement: string }[] = [
  {
    category: "protected_label",
    pattern: /(?:姓名|年龄|出生日期|出生年月|性别|婚育状况|民族|宗教(?:信仰)?|健康状况|残障(?:情况)?|政治(?:面貌|倾向)|性取向|户籍|户口|籍贯|院校|毕业院校)\s*[:：]\s*[^，,；;。\n]+/g,
    replacement: "[已移除个人属性]",
  },
  {
    category: "protected_label_en",
    pattern: /\b(?:name|age|date of birth|gender|sex|marital status|ethnicity|race|religion|health|disability|political affiliation|sexual orientation|school|university|hukou)\s*:\s*[^,;\n.]+/gi,
    replacement: "[已移除个人属性]",
  },
  { category: "email", pattern: /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g, replacement: "[邮箱]" },
  { category: "phone", pattern: /(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)/g, replacement: "[手机号]" },
  {
    category: "id_card",
    pattern: /(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)/g,
    replacement: "[身份证号]",
  },
  { category: "age", pattern: /(?:\d{1,2}|[一二三四五六七八九十]{1,3})\s*(?:岁|周岁)/g, replacement: "[年龄]" },
  { category: "age_birth", pattern: /(?:19|20)\d{2}\s*年\s*(?:出生|生人)/g, replacement: "[出生年份]" },
  { category: "gender", pattern: /(?:性别[:：]\s*(?:男|女))|(?:(?:男|女)性(?:候选人|应聘者)?)/g, replacement: "[性别]" },
  { category: "gender", pattern: /(?<=^|[，,；;。\s])(?:男|女)(?=$|[，,；;。\s])/g, replacement: "[性别]" },
  { category: "gender_en", pattern: /\b(?:male|female|non-binary)\b/gi, replacement: "[性别]" },
  { category: "age_en", pattern: /\b\d{1,3}[ -]+years?[ -]+old\b/gi, replacement: "[年龄]" },
  {
    category: "marital",
    pattern: /(?:已婚|未婚|已育|未育|离异|丧偶)|(?:婚育状况[:：]?\S{0,6})|(?:\d\s*个?(?:孩子|小孩))/g,
    replacement: "[婚育信息]",
  },
  { category: "ethnicity", pattern: /(?:民族[:：]\s*\S{1,6})|(?:汉族|回族|满族|壮族|维吾尔族)/g, replacement: "[民族]" },
  {
    category: "school",
    pattern: /[\u4e00-\u9fa5]{2,12}(?:大学|学院|中学|高中|职业技术学院)/g,
    replacement: "[院校]",
  },
  { category: "hukou", pattern: /(?:户籍|户口)(?:所在地)?[:：]?\s*\S{2,12}/g, replacement: "[户籍]" },
  { category: "political", pattern: /(?:党员|团员|民主党派|政治面貌[:：]?\S{1,6})/g, replacement: "[政治面貌]" },
  { category: "religion", pattern: /(?:信仰)?(?:基督教|天主教|伊斯兰教|佛教|道教|犹太教)|无神论者|穆斯林/g, replacement: "[宗教信息]" },
  { category: "orientation", pattern: /(?:同性恋|异性恋|双性恋|无性恋)/g, replacement: "[性取向]" },
  {
    category: "health",
    pattern: /(?:残疾|残障|患病|疾病史|健康状况[:：]?\S{1,10}|怀孕|孕期|备孕)/g,
    replacement: "[健康信息]",
  },
];

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function redactText(text: string, options: RedactOptions = {}): RedactResult {
  let output = text;
  let redactions = 0;
  const categories = new Set<string>();

  const terms: string[] = [];
  if (options.candidateName && options.candidateName.trim().length >= 2) {
    terms.push(options.candidateName.trim());
  }
  for (const term of options.extraTerms ?? []) {
    if (term && term.trim().length >= 2) terms.push(term.trim());
  }
  for (const term of terms) {
    const pattern = new RegExp(escapeRegExp(term), "g");
    const matches = output.match(pattern);
    if (matches) {
      redactions += matches.length;
      categories.add("name");
      output = output.replace(pattern, "[姓名]");
    }
  }

  for (const rule of PATTERNS) {
    const matches = output.match(rule.pattern);
    if (matches) {
      redactions += matches.length;
      categories.add(rule.category);
      output = output.replace(rule.pattern, rule.replacement);
    }
  }

  return { text: output, redactions, categories: [...categories] };
}

export interface RedactTranscriptTurn {
  seq: number;
  role: string;
  content: string;
}

export interface RedactTranscriptResult {
  turns: { seq: number; role: string; content: string }[];
  redactions: number;
  categories: string[];
}

/** 只对候选人发言做去标识化；面试官提问里也可能带姓名，一并处理。 */
export function redactTranscript(
  turns: readonly RedactTranscriptTurn[],
  options: RedactOptions = {},
): RedactTranscriptResult {
  let redactions = 0;
  const categories = new Set<string>();
  const redacted = turns.map((turn) => {
    const result = redactText(turn.content, options);
    redactions += result.redactions;
    for (const category of result.categories) categories.add(category);
    return { seq: turn.seq, role: turn.role, content: result.text };
  });
  return { turns: redacted, redactions, categories: [...categories] };
}

/** 白名单结构 + 字段内文本脱敏；用于解析输出进入持久化/评分之前。 */
export function sanitizeResumeProfile(input: unknown, options: RedactOptions = {}): ResumeProfile {
  const profile = resumeProfileSchema.parse(input);
  const clean = (value: string): string => redactText(value, options).text;
  return {
    summary: clean(profile.summary),
    experiences: profile.experiences.map((experience) => ({
      company: clean(experience.company),
      title: clean(experience.title),
      start: experience.start,
      end: experience.end,
      highlights: experience.highlights.map(clean),
    })),
    skills: profile.skills.map(clean),
    projects: profile.projects.map((project) => ({ name: clean(project.name), detail: clean(project.detail) })),
    achievements: profile.achievements.map(clean),
  };
}
