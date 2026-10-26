"""Normalization: two job-change vendors, two payload shapes, one internal record.

Everything downstream sees `JobChange`. Adding a vendor means writing one adapter
function here, not touching identity or decision code."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class JobChange:
    provider: str
    provider_event_id: str
    name: str
    profile_url: Optional[str]
    metro: Optional[str]
    new_company: str
    new_domain: str
    new_title: str
    previous_company: Optional[str]
    detected_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z ]", "", (s or "").lower()).strip()


def norm_company(s: Optional[str]) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()
    return " ".join(w for w in words if w not in {"inc", "llc", "the"})


def _jobsignal(p: dict) -> JobChange:
    return JobChange(
        provider="jobsignal", provider_event_id=p["event_id"], name=p["person"]["full_name"],
        profile_url=p["person"].get("profile_url"), metro=p["person"].get("location"),
        new_company=p["new_role"]["company"], new_domain=p["new_role"]["domain"],
        new_title=p["new_role"]["title"], previous_company=(p.get("previous_role") or {}).get("company"),
        detected_at=p["detected_at"])


def _careerwire(p: dict) -> JobChange:
    return JobChange(
        provider="careerwire", provider_event_id=p["id"], name=p["name"], profile_url=p.get("linkedin"),
        metro=p.get("metro"), new_company=p["to_company"], new_domain=p["to_domain"],
        new_title=p["to_title"], previous_company=p.get("from_company"), detected_at=p["observed"])


ADAPTERS = {"jobsignal": _jobsignal, "careerwire": _careerwire}


class PayloadError(ValueError):
    pass


def normalize(provider: str, payload: dict) -> JobChange:
    if provider not in ADAPTERS:
        raise PayloadError(f"unknown provider {provider!r}")
    try:
        jc = ADAPTERS[provider](payload)
    except (KeyError, TypeError) as e:
        raise PayloadError(f"{provider} payload missing field: {e}") from e
    if not jc.name or not jc.new_domain:
        raise PayloadError("name and new company domain are required")
    return jc


def subject_key(jc: JobChange) -> str:
    """Who is this signal about? Used to remember corrections for this person."""
    if jc.profile_url:
        return "url:" + jc.profile_url.lower()
    return f"name:{norm_name(jc.name)}|{jc.new_domain.lower()}"


def move_key(jc: JobChange) -> str:
    """The same move reported by two vendors should collapse into one signal."""
    return f"{norm_name(jc.name)}|{jc.new_domain.lower()}"
