from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BehaviorEventStatus, BehaviorResolutionReason
from app.models import BehaviorEvent


class BehaviorEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_open_by_id_for_update(self, event_id: str) -> BehaviorEvent | None:
        result = await self.session.execute(
            select(BehaviorEvent)
            .where(
                BehaviorEvent.id == event_id,
                BehaviorEvent.status == BehaviorEventStatus.ACTIVE.value,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_open_by_session_and_type_for_update(
        self,
        *,
        session_id: str,
        behavior_type: str,
    ) -> BehaviorEvent | None:
        result = await self.session.execute(
            select(BehaviorEvent)
            .where(
                BehaviorEvent.session_id == session_id,
                BehaviorEvent.behavior_type == behavior_type,
                BehaviorEvent.status == BehaviorEventStatus.ACTIVE.value,
            )
            .order_by(BehaviorEvent.started_at.desc(), BehaviorEvent.id.desc())
            .with_for_update()
        )
        return result.scalars().first()

    async def list_open_by_session_for_update(self, session_id: str) -> list[BehaviorEvent]:
        result = await self.session.execute(
            select(BehaviorEvent)
            .where(
                BehaviorEvent.session_id == session_id,
                BehaviorEvent.status == BehaviorEventStatus.ACTIVE.value,
            )
            .order_by(BehaviorEvent.started_at, BehaviorEvent.id)
            .with_for_update()
        )
        return list(result.scalars().all())

    def add(self, event: BehaviorEvent) -> None:
        self.session.add(event)

    @staticmethod
    def close(
        event: BehaviorEvent,
        *,
        ended_at: datetime,
        resolution_reason: BehaviorResolutionReason,
    ) -> None:
        normalized_ended_at = max(ended_at, event.started_at)
        event.status = BehaviorEventStatus.RESOLVED.value
        event.ended_at = normalized_ended_at
        event.duration_ms = max(
            0,
            int((normalized_ended_at - event.started_at).total_seconds() * 1000),
        )
        event.resolution_reason = resolution_reason.value
