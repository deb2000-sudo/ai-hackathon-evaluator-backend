"""Resolve per-round hackathon settings with legacy hackathon-level fallbacks."""

from __future__ import annotations

from typing import Any


TEAM_MODE_LABELS = {
    1: "Solo",
    2: "2 Members",
    3: "3 Members",
    4: "4 Members",
}


def normalize_max_team_size(value: Any) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = 1
    return max(1, min(4, size))


def hackathon_default_video_required(hackathon: dict[str, Any]) -> bool:
    """Legacy hackathon-level default (true when unset)."""
    return bool(hackathon.get("working_demo_video_required", True))


def hackathon_default_auto_ai(hackathon: dict[str, Any]) -> bool:
    """Legacy hackathon-level default (false when unset)."""
    return bool(hackathon.get("auto_ai_evaluation", False))


def get_timeline_round(
    hackathon: dict[str, Any], round_index: int
) -> dict[str, Any] | None:
    timeline = hackathon.get("timeline") or []
    if round_index < 0 or round_index >= len(timeline):
        return None
    round_ = timeline[round_index]
    return dict(round_) if isinstance(round_, dict) else round_.model_dump()


def round_title(hackathon: dict[str, Any], round_index: int) -> str:
    round_ = get_timeline_round(hackathon, round_index)
    if not round_:
        return f"Round {round_index + 1}"
    return str(round_.get("title") or f"Round {round_index + 1}")


def round_working_demo_video_required(
    hackathon: dict[str, Any], round_index: int
) -> bool:
    round_ = get_timeline_round(hackathon, round_index)
    if round_ is None:
        return hackathon_default_video_required(hackathon)
    if "working_demo_video_required" in round_:
        return bool(round_["working_demo_video_required"])
    return hackathon_default_video_required(hackathon)


def round_auto_ai_evaluation(hackathon: dict[str, Any], round_index: int) -> bool:
    round_ = get_timeline_round(hackathon, round_index)
    if round_ is None:
        return hackathon_default_auto_ai(hackathon)
    if "auto_ai_evaluation" in round_:
        return bool(round_["auto_ai_evaluation"])
    return hackathon_default_auto_ai(hackathon)


def submission_round_index(submission: dict[str, Any]) -> int:
    try:
        return max(0, int(submission.get("round_index", 0)))
    except (TypeError, ValueError):
        return 0


def submission_auto_ai_enabled(
    hackathon: dict[str, Any] | None, submission: dict[str, Any]
) -> bool:
    if not hackathon:
        return False
    if submission.get("auto_ai_evaluation") is not None:
        return bool(submission["auto_ai_evaluation"])
    return round_auto_ai_evaluation(hackathon, submission_round_index(submission))


def enrich_timeline_round(
    round_: dict[str, Any],
    *,
    hackathon: dict[str, Any],
) -> dict[str, Any]:
    """Normalize one timeline round for API responses."""
    data = dict(round_)
    max_size = normalize_max_team_size(data.get("max_team_size", 1))
    data["max_team_size"] = max_size
    data["team_mode_label"] = TEAM_MODE_LABELS.get(max_size, f"{max_size} Members")
    if "working_demo_video_required" not in data:
        data["working_demo_video_required"] = hackathon_default_video_required(hackathon)
    else:
        data["working_demo_video_required"] = bool(data["working_demo_video_required"])
    if "auto_ai_evaluation" not in data:
        data["auto_ai_evaluation"] = hackathon_default_auto_ai(hackathon)
    else:
        data["auto_ai_evaluation"] = bool(data["auto_ai_evaluation"])
    return data
