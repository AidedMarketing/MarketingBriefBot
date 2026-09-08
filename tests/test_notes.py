import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import bot

class NoteTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_draft_preserved_without_model(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(effective_user=SimpleNamespace(id=1), message=message)
        draft = 'My draft\n' + 'x' * 5000
        with patch.object(bot, 'get_active_discussion', return_value={'id': 7}), patch.object(bot, 'get_discussion_history', return_value=[{'role':'assistant','content':draft}]), patch.object(bot, 'save_learning_note') as save, patch.object(bot, 'create_learning_note') as generate:
            await bot.save_note_command(update, None)
            save.assert_called_once_with(1, 7, draft)
            generate.assert_not_called()
            self.assertIn('Note saved', message.reply_text.call_args.args[0])

    async def test_save_failure_not_reported_as_success(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        with patch.object(bot, 'save_learning_note', side_effect=RuntimeError()):
            await bot.persist_note(message, 1, 7, 'draft')
        self.assertIn("couldn't confirm", message.reply_text.call_args.args[0])

    async def test_generation_timeout_does_not_write(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        with patch.object(bot, 'create_learning_note', side_effect=TimeoutError()), patch.object(bot, 'save_learning_note') as save:
            await bot.generate_and_save_note(message, 1, {'id':7}, [])
            save.assert_not_called()
        self.assertIn('/savenote', message.reply_text.call_args.args[0])

    async def test_long_notes_are_split_without_losing_text(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(effective_user=SimpleNamespace(id=1), message=message)
        with patch.object(bot, 'get_learning_notes', return_value=[{'title':'Draft','note':'x'*9000}]):
            await bot.notes(update, None)
        chunks = [c.args[0] for c in message.reply_text.call_args_list]
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 3800 for c in chunks))
        self.assertEqual(sum(c.count('x') for c in chunks), 9000)
