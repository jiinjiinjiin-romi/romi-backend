from app.schemas.base import ApiBaseModel
from app.schemas.profile import ProfileSummaryResponse


class BootstrapCapabilitiesResponse(ApiBaseModel):
    vit_model_available: bool
    gemini_available: bool
    email_available: bool
    demo_mode: bool


class BootstrapAccountResponse(ApiBaseModel):
    id: str
    display_name: str
    email: str | None


class BootstrapResponse(ApiBaseModel):
    account: BootstrapAccountResponse
    profiles: list[ProfileSummaryResponse]
    selected_profile_id: str | None
    profile_limit: int
    capabilities: BootstrapCapabilitiesResponse
