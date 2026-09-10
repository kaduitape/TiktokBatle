from app.schemas.schemas import LiveEvent


class EventNormalizer:
    """Every LiveEventProvider already emits the standard LiveEvent shape
    (section 48). This module is the single choke point that the pipeline
    calls before an event is trusted, so future providers with messier raw
    payloads have exactly one place to normalize into instead of leaking
    provider-specific shapes downstream."""

    @staticmethod
    def normalize(event: LiveEvent) -> LiveEvent:
        if event.type == "gift_received" and event.gift is None:
            raise ValueError("gift_received event missing gift payload")
        if event.gift and event.gift.quantity < 1:
            event.gift.quantity = 1
        return event


event_normalizer = EventNormalizer()
