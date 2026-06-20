from typing import Protocol

from app.models.subscription import SubscriptionPayload


class SubscriptionTransformer(Protocol):
    def transform(self, payload: SubscriptionPayload) -> SubscriptionPayload: ...


class PassthroughTransformer:
    def transform(self, payload: SubscriptionPayload) -> SubscriptionPayload:
        return payload