from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import requests

from app.config import settings


@dataclass(frozen=True)
class ParsedRevisionRequest:
    project_code: str | None
    requested_amount_try: int | None
    justification: str | None
    extracted: dict[str, Any]


_PROJECT_CODE_LABEL_RE = re.compile(
    r"(?im)\bproje\s*(?:kodu|no|numarası|numarasi)\s*[:\-]?\s*(20\d{2})\s*[-/]\s*(\d{3,8})\b"
)
_PROJECT_CODE_RE = re.compile(r"\b(20\d{2})\s*[-/]\s*(\d{3,8})\b")


def _parse_try_amount(raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None

    cleaned = re.sub(r"[^\d.,]", "", raw)
    if not cleaned:
        return None

    if "." in cleaned and "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") >= 1 and re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", cleaned):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")

    try:
        value = float(cleaned)
    except ValueError:
        return None

    if value < 0:
        return None
    return int(round(value))


def _extract_justification(text: str) -> str | None:
    pattern = re.compile(r"(?im)^(gerekçe|gerekce|açıklama|aciklama)\s*[:\-]?\s*$")
    lines = (text or "").splitlines()

    for i, line in enumerate(lines):
        if pattern.match(line.strip()):
            chunk = []
            for j in range(i + 1, min(len(lines), i + 25)):
                if re.match(r"(?im)^[A-ZÇĞİÖŞÜ0-9][A-ZÇĞİÖŞÜ0-9 \t]{3,}$", lines[j].strip()):
                    break
                chunk.append(lines[j])
            result = "\n".join(chunk).strip()
            return result or None

    trimmed = (text or "").strip()
    return trimmed[:800] if trimmed else None


def _parse_with_rules(text: str) -> ParsedRevisionRequest:
    project_code = None
    label_match = _PROJECT_CODE_LABEL_RE.search(text or "")
    if label_match:
        project_code = f"{label_match.group(1)}-{label_match.group(2)}"
    else:
        # Fallback: pick the first match that is not a year-range like 2024-2028.
        for m in _PROJECT_CODE_RE.finditer(text or ""):
            suffix = m.group(2)
            if len(suffix) == 4:
                try:
                    suffix_int = int(suffix)
                    if 1900 <= suffix_int <= 2100:
                        continue
                except Exception:
                    pass
            project_code = f"{m.group(1)}-{m.group(2)}"
            break

    amount = None
    label_amount = re.search(
        r"(?im)\btalep\s*tutar[ıi]\s*[:\-]?\s*([0-9][0-9\.\,\s]{0,20})(?:\s*(?:₺|tl|try))?\b",
        text or "",
    )
    if label_amount:
        amount = _parse_try_amount(label_amount.group(1))

    currency_candidates = []
    currency_candidates += re.findall(r"(?i)(?:₺|tl|try)\s*([0-9][0-9\.\,\s]{0,20})", text or "")
    currency_candidates += re.findall(r"(?i)([0-9][0-9\.\,\s]{0,20})\s*(?:₺|tl|try)\b", text or "")
    for candidate in currency_candidates:
        amount = _parse_try_amount(candidate)
        if amount:
            break
    if amount is None:
        nums = re.findall(r"\b[0-9]{1,3}(?:\.[0-9]{3})+(?:,[0-9]+)?\b", text or "")
        for n in nums:
            amount = _parse_try_amount(n)
            if amount:
                break

    justification = _extract_justification(text)
    extracted = {
        "method": "rules",
        "project_code": project_code,
        "requested_amount_try": amount,
        "justification": justification,
    }
    return ParsedRevisionRequest(project_code=project_code, requested_amount_try=amount, justification=justification, extracted=extracted)


def _parse_with_openai(text: str) -> ParsedRevisionRequest:
    api_key = (settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")).strip()
    if not api_key:
        return _parse_with_rules(text)

    prompt = {
        "role": "system",
        "content": (
            "Sen bir kamu yatırım dokümanı okuyucususun. Kullanıcı metninden yatırım programı revizyon talebini çıkar.\n"
            "Sadece JSON döndür (başka metin yok). JSON alanları:\n"
            "- project_code: 'YYYY-123456' formatında proje kodu (yoksa null)\n"
            "- requested_amount_try: Türk Lirası cinsinden tam sayı (yoksa null)\n"
            "- justification: gerekçe metni (yoksa null)\n"
            "- confidence: 0..1\n"
        ),
    }
    user = {"role": "user", "content": text[:12000]}

    payload = {
        "model": settings.openai_model,
        "messages": [prompt, user],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    parsed = json.loads(content)

    project_code = parsed.get("project_code")
    amount = parsed.get("requested_amount_try")
    justification = parsed.get("justification")

    try:
        amount_int = int(amount) if amount is not None else None
    except Exception:
        amount_int = None

    extracted = {"method": "openai", **parsed}
    return ParsedRevisionRequest(project_code=project_code, requested_amount_try=amount_int, justification=justification, extracted=extracted)


def parse_revision_request(text: str) -> ParsedRevisionRequest:
    provider = (settings.llm_provider or "mock").strip().lower()
    if provider == "openai":
        try:
            return _parse_with_openai(text)
        except Exception as e:
            parsed = _parse_with_rules(text)
            parsed.extracted["openai_error"] = str(e)
            return parsed
    return _parse_with_rules(text)
