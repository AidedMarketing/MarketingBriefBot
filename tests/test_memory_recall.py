import unittest
from unittest.mock import MagicMock, patch

import ai_provider
import bot
import database


class RelatedLearningNoteTests(unittest.TestCase):
    def test_database_lookup_is_limited_to_same_topic_and_user(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [{"note": "A saved idea", "title": "Earlier article"}]

        with patch.object(database, "get_connection", return_value=connection):
            rows = database.get_related_learning_notes(user_id=9, article_id=24, limit=9)

        self.assertEqual(rows, [{"note": "A saved idea", "title": "Earlier article"}])
        query, params = cursor.execute.call_args.args
        self.assertIn("note.user_id=%s", query)
        self.assertIn("prior.topic=current_article.topic", query)
        self.assertIn("note.article_id <> current_article.id", query)
        self.assertEqual(params, (24, 9, 3))

    def test_bot_attaches_only_a_small_note_set(self):
        article = {"id": 24, "title": "Current article"}
        notes = [{"title": "Earlier article", "note": "A saved idea"}]

        with patch.object(bot, "get_related_learning_notes", return_value=notes) as lookup:
            enriched = bot.attach_related_learning_notes(article, user_id=9)

        lookup.assert_called_once_with(9, 24, limit=2)
        self.assertEqual(enriched["related_learning_notes"], notes)
        self.assertNotIn("related_learning_notes", article)

    def test_model_context_separates_prior_notes_from_article_evidence(self):
        article = {
            "id": 24,
            "title": "Current article",
            "publication": "HBR",
            "topic": "Strategy",
            "url": "https://example.com/current",
            "content_status": "full",
            "related_learning_notes": [
                {"title": "Earlier article", "note": "A saved idea from last week"}
            ],
        }

        context = ai_provider._article_context(article)

        self.assertIn("A saved idea from last week", context)
        self.assertIn("personal context only; not evidence about this article", context)
        self.assertIn("Earlier article", context)


if __name__ == "__main__":
    unittest.main()
