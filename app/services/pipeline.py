from app.models.subscription import SubscriptionPayload
from app.services.transformer import SubscriptionTransformer


class TransformerPipeline:
    def __init__(self, steps: list[SubscriptionTransformer]) -> None:
        self._steps = steps

    def transform(self, payload: SubscriptionPayload) -> SubscriptionPayload:
        current = payload
        for step in self._steps:
            current = step.transform(current)
        return current