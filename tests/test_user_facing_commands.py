import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import bot


class UserFacingCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_help_explains_today_and_next(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(message=message)

        await bot.start(update, None)

        help_text = message.reply_text.await_args.args[0]
        self.assertIn("/today — Today's pick (same article all day)", help_text)
        self.assertIn("/next — Another unseen article", help_text)


if __name__ == "__main__":
    unittest.main()
