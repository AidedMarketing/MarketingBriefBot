import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import app
import database
from daily_brief import _daily_brief_frame, get_today_article


class DailyDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def run_delivery(self, fail=False):
        article = dict(id=7, title='A read', publication='HBR', url='https://hbr.org/x',
                       topic='Strategy', reading_time=5, content_status='full', word_count=900)
        message = SimpleNamespace(reply_text=AsyncMock(side_effect=RuntimeError('send failed') if fail else None))
        update = SimpleNamespace(effective_user=SimpleNamespace(id=1), message=message)
        events = []
        if not fail:
            message.reply_text.side_effect = lambda *a, **kw: events.append('sent')
        with patch.object(app, '_schedule_source_refresh'), patch.object(app, '_schedule_article_enrichment'), \
             patch.object(app, 'get_daily_article', return_value=article), \
             patch.object(app.bot, 'attach_reader_context', side_effect=lambda a, u: a), \
             patch.object(app.bot, 'article_keyboard', return_value=None), \
             patch.object(app.bot, 'start_discussion', side_effect=lambda *a: events.append('activated')), \
             patch.object(app.bot, 'record_activity', side_effect=lambda *a: events.append('recorded')) as record:
            if fail:
                with self.assertRaises(RuntimeError):
                    await app.daily_today(update, None)
                record.assert_not_called()
            else:
                await app.daily_today(update, None)
                self.assertEqual(events, ['sent', 'activated', 'recorded'])
                record.assert_called_once_with(7, 'delivered', 1, True)

    async def test_failed_send_does_not_consume_article(self):
        await self.run_delivery(fail=True)

    async def test_success_is_recorded_after_send(self):
        await self.run_delivery()


class DatabaseTests(unittest.TestCase):
    def connection(self, rows):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = rows
        return connection, cursor

    def test_daily_selection_refreshes_reader_facing_explanation(self):
        connection, cursor = self.connection([{
            'id': 7,
            'title': 'Brand Strategy: EV naming',
            'topic': 'Brand Strategy',
            'frame': {'daily_reason': 'Old scoring explanation'},
        }])
        with patch('daily_brief.get_connection', return_value=connection):
            result = get_today_article(1)
        self.assertIn('positioning work', result['daily_reason'])
        self.assertNotIn('Old scoring explanation', result['daily_reason'])
        self.assertNotIn('frame', result)
        self.assertEqual(cursor.execute.call_count, 2)

    def test_force_new_skips_daily_cache_and_excludes_delivered_articles(self):
        article = {
            'id': 24,
            'title': 'A fresh read',
            'publication': 'Marketing Brew',
            'topic': 'Strategy',
            'reading_time': 5,
        }
        connection, cursor = self.connection([article])

        with patch('daily_brief.get_connection', return_value=connection):
            result = get_today_article(1, force_new=True)

        self.assertEqual(result['id'], 24)
        statements = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertFalse(any('FROM daily_briefs d' in statement for statement in statements))
        candidate_sql = next(statement for statement in statements if 'WITH topic_memory' in statement)
        self.assertIn("seen.action='delivered'", candidate_sql)
        self.assertIn('NOT EXISTS', candidate_sql)


    def test_note_memory_uses_same_transaction(self):
        connection, _ = self.connection([])
        with patch.object(database, 'get_connection', return_value=connection), \
             patch.object(database, 'update_learning_memory') as memory:
            database.save_learning_note(1, 7, 'A useful idea')
        memory.assert_called_once_with(1, 7, 'note_saved', connection=connection)

    def test_import_is_private_and_does_not_claim_completeness(self):
        connection, cursor = self.connection([
            {'article_id': 7, 'buffer_text': 'word ' * 400, 'source_type': 'user_paste'},
            {'id': 7, 'content_status': 'metadata_only'},
        ])
        with patch.object(database, 'get_connection', return_value=connection):
            article = database.finish_import(1)
        writes = [call.args for call in cursor.execute.call_args_list if 'INSERT INTO' in call.args[0]]
        self.assertEqual(len(writes), 1)
        self.assertIn('INSERT INTO reader_excerpts', writes[0][0])
        self.assertEqual(writes[0][1][:2], (1, 7))
        self.assertEqual(article['content_status'], 'metadata_only')
        self.assertEqual(article['imported_word_count'], 400)

    def test_empty_import_keeps_session_open(self):
        connection, cursor = self.connection([{'article_id': 7, 'buffer_text': ''}])
        with patch.object(database, 'get_connection', return_value=connection):
            self.assertIsNone(database.finish_import(1))
        self.assertEqual(cursor.execute.call_count, 1)

    def test_repeated_source_does_not_claim_rotation(self):
        result = _daily_brief_frame({'recent_pub_count': 3, 'topic': 'Strategy'})
        self.assertNotEqual(result['reading_mode'], 'Balance')
        self.assertNotIn('penalty', result['daily_reason'].lower())
        self.assertIn('strategy', result['daily_reason'].lower())


if __name__ == '__main__':
    unittest.main()
