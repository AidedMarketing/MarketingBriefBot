import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import app
import bot
import jev_pilot
from jev import JevConfig
from test_jev import provider_response


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.article = {'id': 7, 'title': 'Public article', 'plain_text': 'Stored body', 'content_status': 'partial'}
        self.config = JevConfig('shadow', 'test-key')

    def test_disabled_pilot_does_not_touch_database(self):
        with patch('jev_pilot.get_article') as read:
            self.assertEqual(jev_pilot.evaluate_stored_article(self.article, JevConfig())['status'], 'disabled')
        read.assert_not_called()

    def test_evaluates_committed_text_and_saves_once(self):
        result = {'status': 'ok', 'fingerprint': 'key'}
        with patch('jev_pilot.get_article', return_value=self.article), \
             patch('jev_pilot.get_jev_evaluation', return_value=None), \
             patch('jev_pilot.evaluate_article', return_value=result) as provider, \
             patch('jev_pilot.save_jev_evaluation') as save:
            self.assertEqual(jev_pilot.evaluate_stored_article(dict(self.article, plain_text='Rejected new extraction'), self.config), result)
        provider.assert_called_once_with(self.article, self.config)
        save.assert_called_once_with(7, result)

    def test_successful_and_skipped_results_are_cached(self):
        for status in ('ok', 'skipped_empty', 'skipped_oversized'):
            with patch('jev_pilot.get_article', return_value=self.article), \
                 patch('jev_pilot.get_jev_evaluation', return_value={'result': {'status': status}, 'recent': False}), \
                 patch('jev_pilot.evaluate_article') as provider:
                result = jev_pilot.evaluate_stored_article(self.article, self.config)
            self.assertTrue(result['cached'])
            provider.assert_not_called()

    def test_recent_errors_cool_down_and_old_errors_retry(self):
        for recent in (True, False):
            with patch('jev_pilot.get_article', return_value=self.article), \
                 patch('jev_pilot.get_jev_evaluation', return_value={'result': {'status': 'error'}, 'recent': recent}), \
                 patch('jev_pilot.evaluate_article', return_value={'status': 'ok', 'fingerprint': 'key'}) as provider, \
                 patch('jev_pilot.save_jev_evaluation'):
                jev_pilot.evaluate_stored_article(self.article, self.config)
            self.assertEqual(provider.call_count, 0 if recent else 1)

    def test_database_failure_does_not_escape_and_lock_is_released(self):
        with patch('jev_pilot.get_article', side_effect=RuntimeError('private details')):
            result = jev_pilot.evaluate_stored_article(self.article, self.config)
        self.assertEqual(result['error_type'], 'pilot_unavailable')
        self.assertNotIn('private', str(result))
        self.assertFalse(jev_pilot._evaluation_lock.locked())

    def test_concurrent_evaluation_is_coalesced(self):
        jev_pilot._evaluation_lock.acquire()
        try:
            with patch('jev_pilot.get_article') as read:
                result = jev_pilot.evaluate_stored_article(self.article, self.config)
            self.assertEqual(result['status'], 'busy')
            read.assert_not_called()
        finally:
            jev_pilot._evaluation_lock.release()

    def test_report_labels_are_explicit_about_shadow_and_completeness(self):
        result = dict(provider_response(), status='ok', rubric_version='brief-pilot-1', word_count=99)
        output = jev_pilot.format_evaluation(result)
        self.assertIn('does not change your daily pick', output)
        self.assertIn('do not prove article completeness', output)


class PilotCommandTests(unittest.IsolatedAsyncioTestCase):
    def update(self):
        return SimpleNamespace(effective_user=SimpleNamespace(id=1),
                               message=SimpleNamespace(reply_text=AsyncMock()))

    async def test_missing_key_has_clear_setup_message(self):
        update = self.update()
        with patch('bot.JevConfig.from_env', return_value=JevConfig('shadow')):
            await bot.jev_command(update, SimpleNamespace(args=[]))
        self.assertIn('TYPESAFE_API_KEY', update.message.reply_text.await_args.args[0])

    async def test_manual_evaluation_uses_public_article_not_private_context(self):
        update = self.update()
        article = {'id': 7, 'title': 'Public article'}
        with patch('bot.JevConfig.from_env', return_value=JevConfig('shadow', 'key')), \
             patch('bot.get_history', return_value=[{'id': 7}]), \
             patch('bot.get_article', return_value=article), \
             patch('bot.evaluate_stored_article', return_value={'status': 'skipped_empty'}) as evaluate, \
             patch('bot.attach_reader_context') as private:
            await bot.jev_command(update, SimpleNamespace(args=['evaluate']))
        evaluate.assert_called_once_with(article, JevConfig('shadow', 'key'))
        private.assert_not_called()

    async def test_daily_delivery_schedules_full_article_after_send(self):
        update = self.update()
        article = {'id': 7, 'title': 'Public article', 'publication': 'HBR', 'url': 'https://hbr.org/x',
                   'topic': 'Strategy', 'content_status': 'full', 'reading_time': 5}
        events = []
        update.message.reply_text.side_effect = lambda *a, **kw: events.append('sent')
        with patch('app._schedule_source_refresh'), patch('app.get_daily_article', return_value=article), \
             patch('app.bot.attach_reader_context', side_effect=lambda a, u: a), \
             patch('app.bot.article_keyboard', return_value=None), patch('app.bot.start_discussion'), \
             patch('app.bot.record_activity'), \
             patch('app._schedule_jev_evaluation', side_effect=lambda a: events.append('evaluation')):
            await app.daily_today(update, None)
        self.assertEqual(events, ['sent', 'evaluation'])


if __name__ == '__main__':
    unittest.main()
