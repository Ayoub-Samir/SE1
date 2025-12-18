from __future__ import annotations

from dataclasses import dataclass

from app.db import Project


@dataclass(frozen=True)
class RiskResult:
    score: int  # 0..100
    notes: str


def calculate_risk(project: Project | None, requested_amount_try: int | None, justification: str | None) -> RiskResult:
    score = 0
    notes: list[str] = []

    if project is None:
        score += 35
        notes.append("Proje kodu veritabanında bulunamadı (referans kontrolü gerekli).")
        return RiskResult(score=min(100, score), notes=" ".join(notes))

    if requested_amount_try is None:
        score += 30
        notes.append("Talep tutarı çıkarılamadı; manuel doğrulama gerekli.")
    else:
        if requested_amount_try > project.remaining_try:
            score += 50
            notes.append("Talep tutarı kalan bütçeyi aşıyor.")

        if project.spent_ratio >= 0.9:
            score += 15
            notes.append("Harcama oranı %90+; revizyon etkisi yüksek olabilir.")

        if project.total_budget_try > 0 and (requested_amount_try / project.total_budget_try) >= 0.2:
            score += 15
            notes.append("Talep, toplam bütçenin %20+ seviyesinde.")

        if requested_amount_try <= 0:
            score += 20
            notes.append("Talep tutarı geçersiz (<=0).")

    if not justification or len(justification.strip()) < 50:
        score += 10
        notes.append("Gerekçe çok kısa; detay iste.")

    return RiskResult(score=min(100, score), notes=" ".join(notes) if notes else "Belirgin risk sinyali yok.")

