from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentConversation


class AgentConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, conversation: AgentConversation) -> None:
        self.session.add(conversation)
