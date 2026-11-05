from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import TypeAdapter

from .contracts import Object, ResumeProfile, json_object
from .errors import DomainError

PROTECTED = re.compile(r"年龄|性别|婚育|婚姻|民族|宗教|健康状况|残障|政治倾向|性取向|户籍|家庭情况|家庭背景|家庭收入|父母|亲属|子女|毕业院校")
INJECTION = re.compile(r"忽略.{0,12}(?:指令|规则)|给我.{0,8}(?:满分|最高分|5分)|(?:输出|打印).{0,8}(?:系统提示|提示词)|"
                       r"(?:告诉我|展示).{0,8}(?:规则|系统提示)|(?:你现在是|从现在开始你是).{0,12}(?:管理员|评分系统)|"
                       r"DAN模式|开发者模式|ignore.{0,30}(?:instructions|rules)|perfect score|system prompt|"
                       r"<<<|\[INST\]|<\|(?:system|im_start)|^\s*(?:system|developer)\s*:", re.I)
SENTINEL = "AII_SENTINEL_DO_NOT_REVEAL"


def redact(text: str, name: str = "") -> str:
    result = text
    if name:
        result = result.replace(name, "[姓名已隐去]")
    for pattern, replacement in [
        (r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[邮箱已隐去]"),
        (r"(?<!\d)1[3-9]\d{9}(?!\d)", "[电话已隐去]"),
        (r"(?<!\d)\d{17}[\dXx](?!\d)", "[证件已隐去]"),
        (r"(?:姓名|name)\s*[:：]\s*[^，,。;；\n]+", "[姓名已隐去]"),
        (r"(?:年龄|性别|婚育|婚姻|民族|宗教|健康状况|残障|政治倾向|性取向|户籍|院校|学校|毕业院校|家庭情况|家庭背景|家庭收入|父母|亲属|子女|"
         r"gender|age|sex|marital status|religion|disability|ethnicity|nationality|university)\s*[:：]\s*[^，,。;；\n]+", "[无关属性已剔除]"),
        (r"(?:\d{1,2}岁|已婚|未婚|已育|未育|怀孕|备孕|男士|女士)", "[无关属性已剔除]"),
        (r"[\u4e00-\u9fa5A-Za-z]{2,25}(?:大学|学院|University|College)", "[院校已隐去]"),
    ]:
        result = re.sub(pattern, replacement, result, flags=re.I)
    return result


def assessment_text(text: str, name: str = "") -> str:
    return "".join(part for part in re.split(r"(?<=[。！？!?；;\n])", redact(text, name)) if not INJECTION.search(part))


def safe_question(text: str) -> str:
    if PROTECTED.search(text) or re.search(r"\b(?:age|gender|marital|religion|pregnan|ethnicity|sexual orientation)\b", text, re.I):
        raise DomainError("LLM_STRUCTURED_OUTPUT_INVALID", "题目包含与岗位无关的受保护属性")
    return guard_output(text)


def guard_output(text: str) -> str:
    if re.search(r"AII_SENTINEL|DO_NOT_REVEAL|SCORING_SYSTEM_PROMPT|QUESTION_SYSTEM_PROMPT", text, re.I):
        raise DomainError("LLM_STRUCTURED_OUTPUT_INVALID", "输出未通过提示泄露检查")
    return text


def sanitize_profile(value: object, name: str = "") -> ResumeProfile:
    profile = ResumeProfile.model_validate(value)
    data = profile.payload()

    def clean(item: object) -> object:
        if isinstance(item, str):
            return redact(item, name)
        if isinstance(item, list):
            return [clean(row) for row in item]
        if isinstance(item, dict):
            return {key: clean(row) for key, row in item.items()}
        return item
    return ResumeProfile.model_validate(clean(data))


def sanitize_metadata(value: object, depth: int = 0) -> Object:
    def clean(item: object, level: int) -> object:
        if level > 8:
            return "[TRUNCATED]"
        if isinstance(item, str):
            return redact(item)
        if isinstance(item, bool) or item is None:
            return item
        if isinstance(item, (int, float)):
            masked = redact(str(item))
            return item if masked == str(item) else masked
        if isinstance(item, list):
            return [clean(row, level + 1) for row in item[:100]]
        if isinstance(item, dict):
            return {str(key): "[REDACTED]" if re.match(r"^(password|secret|apiKey|authorization|inviteToken|accessCode)$", str(key), re.I)
                    else clean(row, level + 1) for key, row in list(item.items())[:100]}
        return None
    return json_object(clean(value, depth))


def load_resource(name: str) -> Object:
    return json_object(json.loads((Path(__file__).parent / "resources" / name).read_text("utf-8")))


def consent(mode: str, camera: bool, track: str, days: int = 90) -> tuple[str, str]:
    data = load_resource("consents.json")[f"{mode}:{str(camera).lower()}:{track}"]
    row = TypeAdapter(dict[str, str]).validate_python(data)
    version, text = row["version"], row["text"]
    if days != 90:
        version += f"-retention-{days}-v1"
        text = re.sub(r"90\s*天", f"{days}天", text)
    return version, text


def json_hash(value: object) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
