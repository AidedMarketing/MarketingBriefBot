import unittest

from daily_brief import _daily_brief_frame


class DailyBriefFrameTests(unittest.TestCase):
    def test_ev_naming_card_uses_a_specific_brand_strategy_lens(self):
        frame = _daily_brief_frame({
            "title": "Brand Strategy: What’s in a name? EV naming trends evolve to match the market",
            "topic": "Brand Strategy",
            "recent_pub_count": 4,
            "topic_exposure": 1,
            "topic_engaged": 0,
        })

        self.assertIn("positioning work", frame["daily_reason"])
        self.assertIn("vehicle", frame["learning_objective"])
        self.assertIn("buyer research", frame["learning_objective"])
        self.assertNotIn("repetition penalty", frame["daily_reason"])

    def test_general_card_uses_a_practical_decision_focus(self):
        frame = _daily_brief_frame({
            "title": "A current business article",
            "topic": "Leadership",
        })

        self.assertIn("Leadership", frame["daily_reason"])
        self.assertIn("decision or trade-off", frame["learning_objective"])
        self.assertIn("applying the same approach", frame["learning_objective"])


if __name__ == "__main__":
    unittest.main()
