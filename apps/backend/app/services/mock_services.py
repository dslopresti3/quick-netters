from datetime import date

from app.services.interfaces import OddsProvider, ProjectionsProvider, RecommendationsProvider, ScheduleProvider


class MockScheduleService(ScheduleProvider):
    def fetch(self, selected_date: date) -> list[dict]:
        return [
            {
                "match_id": "m-001",
                "selected_date": selected_date.isoformat(),
                "player_a": "Iga S.",
                "player_b": "Aryna S.",
                "tournament": "Mock Open",
            }
        ]


class MockProjectionsService(ProjectionsProvider):
    def fetch(self, selected_date: date) -> list[dict]:
        return [
            {
                "selected_date": selected_date.isoformat(),
                "player": "Iga S.",
                "win_probability": 0.58,
                "source": "mock-model-v0",
            }
        ]


class MockOddsService(OddsProvider):
    def fetch(self, selected_date: date) -> list[dict]:
        return [
            {
                "selected_date": selected_date.isoformat(),
                "match_id": "m-001",
                "sportsbook": "MockBook",
                "player_a": -130,
                "player_b": 115,
            }
        ]


class MockRecommendationsService(RecommendationsProvider):
    def fetch(self, selected_date: date) -> list[dict]:
        return [
            {
                "selected_date": selected_date.isoformat(),
                "match_id": "m-001",
                "confidence": 0.63,
                "explanation": "Placeholder recommendation generated from mock blended edges.",
            }
        ]
