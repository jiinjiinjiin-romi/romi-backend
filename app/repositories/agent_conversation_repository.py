from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentConversation, AgentMessage, DriverProfile, DrivingSession


class AgentConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, conversation: AgentConversation) -> None:
        self.session.add(conversation)

    async def get_owned_by_id(
        self,
        *,
        conversation_id: str,
        account_id: str,
    ) -> AgentConversation | None:
        result = await self.session.execute(
            select(AgentConversation)
            .join(DrivingSession, AgentConversation.session_id == DrivingSession.id)
            .join(DriverProfile, DrivingSession.profile_id == DriverProfile.id)
            .where(
                AgentConversation.id == conversation_id,
                DriverProfile.account_id == account_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_messages(self, *, conversation_id: str) -> list[AgentMessage]:
        result = await self.session.execute(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(
                AgentMessage.sequence_no.asc(),
                AgentMessage.created_at.asc(),
                AgentMessage.id.asc(),
            )
        )
        return list(result.scalars().all())
