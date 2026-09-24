import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app


class TodayDiscussionActivationTests(unittest.IsolatedAsyncioTestCase):
    async def test_delivered_today_article_becomes_active_before_activity_recording(self):
        article = {"id": 42, "content_status": "full"}
        events = []

        async def reply_text(*args, **kwargs):
            events.append("sent")

        def activate(user_id, article_id):
            events.append("activated")

        def record(*args):
            events.append("recorded")

        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=7),
            message=SimpleNamespace(reply_text=AsyncMock(side_effect=reply_text)),
        )

        with (
            patch.object(app, "_schedule_source_refresh"),
            patch.object(app, "_schedule_article_enrichment"),
            patch.object(app, "get_daily_article", return_value=article),
            patch.object(app, "_format_article", return_value="today's brief"),
            patch.object(app.bot, "attach_reader_context", return_value=article),
            patch.object(app.bot, "article_keyboard", return_value=None),
            patch.object(app.bot, "start_discussion", side_effect=activate),
            patch.object(app.bot, "record_activity", side_effect=record),
        ):
            await app.daily_today(update, None)

        self.assertEqual(events[:3], ["sent", "activated", "recorded"])

    async def test_failed_telegram_send_does_not_activate_undelivered_article(self):
        article = {"id": 42, "content_status": "full"}
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=7),
            message=SimpleNamespace(
                reply_text=AsyncMock(side_effect=RuntimeError("Telegram unavailable"))
            ),
        )

        with (
            patch.object(app, "_schedule_source_refresh"),
            patch.object(app, "_schedule_article_enrichment"),
            patch.object(app, "get_daily_article", return_value=article),
            patch.object(app, "_format_article", return_value="today's brief"),
            patch.object(app.bot, "attach_reader_context", return_value=article),
            patch.object(app.bot, "article_keyboard", return_value=None),
            patch.object(app.bot, "start_discussion") as start_discussion,
            patch.object(app.bot, "record_activity") as record_activity,
        ):
            with self.assertRaisesRegex(RuntimeError, "Telegram unavailable"):
                await app.daily_today(update, None)

        start_discussion.assert_not_called()
        record_activity.assert_not_called()


if __name__ == "__main__":
    unittest.main()
