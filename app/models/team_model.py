"""Hackathon team enrollment and join-code schemas (scoped per timeline round)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.string_utils import strip_required


class TeamMemberSummary(BaseModel):
    user_id: str
    name: str
    email: str
    role: Literal["leader", "member"]
    joined_at: str


class JoinTeamRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        code = strip_required(value)
        if not code.isdigit():
            raise ValueError("Join code must be 6 digits")
        return code


class TeamJoinCodeResponse(BaseModel):
    code: str = Field(..., description="Plaintext 6-digit code (shown once to the leader)")
    expires_at: str
    expires_in_seconds: int


class HackathonTeamResponse(BaseModel):
    id: str
    hackathon_id: str
    round_index: int
    round_title: str
    team_name: str
    leader_id: str
    max_members: int
    member_count: int
    members: list[TeamMemberSummary]
    is_full: bool


class CreateTeamResponse(BaseModel):
    team: HackathonTeamResponse
    join_code: TeamJoinCodeResponse


class JoinTeamResponse(BaseModel):
    team: HackathonTeamResponse
    message: str = "You joined the team successfully"


class HackathonParticipationResponse(BaseModel):
    hackathon_id: str
    round_index: int
    round_title: str
    max_team_size: int
    team_mode_label: str
    working_demo_video_required: bool = True
    auto_ai_evaluation: bool = False
    enrolled: bool
    role: Literal["solo", "leader", "member"] | None = None
    team: HackathonTeamResponse | None = None
    can_submit: bool
    pending_action: Literal["solo_enroll", "choose_role", "create_or_join", "ready"] | None = None
