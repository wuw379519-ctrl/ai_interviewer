from __future__ import annotations

import hashlib
import io
import struct
import threading
import time
import wave
from typing import TYPE_CHECKING

from fastapi import Request
from python_multipart import FormParser
from python_multipart.multipart import Field, File, parse_options_header

from .errors import DomainError
from .service import Result

if TYPE_CHECKING:
    from .service import Service

MAX_AUDIO_BYTES = 16000 * 2 * 120 + 44
preview_lock = threading.RLock()


async def read_limited(request: Request, maximum: int) -> bytes:
    try:
        size = int(request.headers.get("content-length", "0"))
    except ValueError as error:
        raise DomainError("VALIDATION_FAILED", "请求长度无效") from error
    if size > maximum:
        raise DomainError("VALIDATION_FAILED", "请求体超过允许大小")
    output = bytearray()
    async for chunk in request.stream():
        if len(output) + len(chunk) > maximum:
            raise DomainError("VALIDATION_FAILED", "请求体超过允许大小")
        output.extend(chunk)
    return bytes(output)


def memory_upload(content: bytes, content_type: str, field: str) -> tuple[bytes, str, str]:
    kind, options = parse_options_header(content_type.encode())
    if kind != b"multipart/form-data" or b"boundary" not in options:
        raise DomainError("VALIDATION_FAILED", "请提供有效的文件表单")
    files: list[tuple[bytes, str, str]] = []

    def on_field(_value: Field) -> None:
        raise DomainError("VALIDATION_FAILED", "不接受额外表单字段")

    def on_file(value: File) -> None:
        try:
            if files or value.field_name != field.encode() or not value.file_name or not value.in_memory:
                raise DomainError("VALIDATION_FAILED", "仅接受一个指定的内存文件，不接受视频或额外字段")
            value.file_object.seek(0)
            files.append((value.file_object.read(), value.file_name.decode("utf-8", errors="replace"),
                          value.content_type or "application/octet-stream"))
        finally:
            value.close()
    try:
        parser = FormParser("multipart/form-data", on_field, on_file, boundary=options[b"boundary"],
                            config={"MAX_BODY_SIZE": MAX_AUDIO_BYTES + 65536, "MAX_MEMORY_FILE_SIZE": MAX_AUDIO_BYTES + 65536,
                                    "MAX_FIELDS": 1, "MAX_FIELD_SIZE": 0, "UPLOAD_ERROR_ON_BAD_CTE": True})
        parser.write(content)
        parser.finalize()
    except (ValueError, OSError) as error:
        raise DomainError("VALIDATION_FAILED", "文件表单无法读取") from error
    if len(files) != 1:
        raise DomainError("VALIDATION_FAILED", "缺少指定文件")
    return files[0]


def validate_wave(content: bytes) -> None:
    if len(content) < 46 or len(content) > MAX_AUDIO_BYTES or len(content) % 2:
        raise DomainError("VALIDATION_FAILED", "仅接受120秒以内16kHz单声道PCM WAV")
    if content[:4] != b"RIFF" or content[8:16] != b"WAVEfmt " or content[36:40] != b"data":
        raise DomainError("VALIDATION_FAILED", "仅接受音频WAV，不接受视频或其他容器")
    header = struct.unpack("<IHHIIHH", content[16:36])
    if header != (16, 1, 1, 16000, 32000, 2, 16) or struct.unpack("<I", content[4:8])[0] != len(content) - 8 or struct.unpack("<I", content[40:44])[0] != len(content) - 44:
        raise DomainError("VALIDATION_FAILED", "音频格式不匹配")
    try:
        with wave.open(io.BytesIO(content), "rb") as source:
            if source.getnframes() > 16000 * 120:
                raise DomainError("VALIDATION_FAILED", "音频超过120秒")
    except wave.Error as error:
        raise DomainError("VALIDATION_FAILED", "音频无法读取") from error


def check_speech(service: Service, request: Request, identity: str) -> None:
    with service.database.unit_of_work() as connection:
        row = service.candidate_access(connection, request, identity, True, False)
        service.interview(connection, identity, True)
        if row["mode"] != "voice" or row["text_fallback"] or row.get("paused_at"):
            raise DomainError("RESOURCE_CONFLICT", "请在语音面试继续状态下主动输入")
        service.media_ready(row)


def transcribe(service: Service, request: Request, identity: str, content: bytes) -> Result:
    validate_wave(content)
    check_speech(service, request, identity)
    settings = service.settings
    if settings.stt_provider != "whisper" and (not settings.stt_base_url or not settings.stt_model):
        raise DomainError("SPEECH_UNAVAILABLE", "尚未配置企业语音服务，请使用设备端识别或文字")
    key = request.headers.get("idempotency-key", "")
    if len(key) > 200:
        raise DomainError("VALIDATION_FAILED", "幂等键过长")
    fingerprint, scope = hashlib.sha256(content).hexdigest(), identity + ":" + key
    with preview_lock:
        current = time.monotonic()
        service.speech_cache = {key: value for key, value in service.speech_cache.items() if value[2] > current}
        cached = service.speech_cache.get(scope) if key else None
        if cached and cached[0] != fingerprint:
            raise DomainError("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_BODY", "音频幂等键对应不同内容")
        if cached:
            text = cached[1]
        else:
            service.auth.limit(f"speech:{identity}", 10)
            with service.database.unit_of_work() as connection:
                text = service.gateway.transcribe(content, connection=connection)
            # Recheck after a slow network call; erasure/revocation must prevent preview delivery.
            check_speech(service, request, identity)
            if key:
                if len(service.speech_cache) >= 50:
                    service.speech_cache.pop(next(iter(service.speech_cache)))
                service.speech_cache[scope] = fingerprint, text, time.monotonic() + 60, identity
            with service.database.unit_of_work() as connection:
                service.audit(connection, "speech.transcribed", identity, {"bytes": len(content), "audioStored": False, "previewStored": False, "vendor": "local_whisper" if settings.stt_provider == "whisper" else "configured_http_stt", "audioSeconds": (len(content) - 44) / 32000, "durationMs": round((time.monotonic() - current) * 1000)}, interview_id=identity)
        check_speech(service, request, identity)
        return Result({"text": text})


def parse_resume_file(content: bytes, file_name: str, mime: str) -> tuple[str, str]:
    if len(content) > 2 * 1024 * 1024:
        raise DomainError("VALIDATION_FAILED", "简历文件超过2MiB")
    try:
        if file_name.lower().endswith(".pdf") and mime in {"application/pdf", "application/octet-stream"}:
            from pypdf import PdfReader
            document = PdfReader(io.BytesIO(content))
            if document.is_encrypted or len(document.pages) > 20:
                raise ValueError("encrypted or too many pages")
            text = "\n".join(page.extract_text() or "" for page in document.pages)
            actual_mime = "application/pdf"
        elif file_name.lower().endswith(".docx"):
            import zipfile
            from docx import Document
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if sum(row.file_size for row in archive.infolist()) > 16 * 1024 * 1024 or len(archive.infolist()) > 500:
                    raise ValueError("archive too large")
            source = Document(io.BytesIO(content))
            text = "\n".join([paragraph.text for paragraph in source.paragraphs] +
                             [cell.text for table in source.tables for row in table.rows for cell in row.cells])
            actual_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            raise ValueError("format")
    except Exception as error:
        raise DomainError("VALIDATION_FAILED", "无法读取简历；请使用文字版PDF/DOCX或粘贴文本") from error
    if not 20 <= len(text.strip()) <= 30000:
        raise DomainError("VALIDATION_FAILED", "简历提取文字须为20至30000字，扫描件请改用文字")
    return text.strip(), actual_mime
