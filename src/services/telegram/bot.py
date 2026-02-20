from __future__ import annotations

from telegram.ext import Application

from src.services.telegram.commands import CommandDependencies, build_command_handlers


def build_application(*, bot_token: str, deps: CommandDependencies) -> Application:
    app = Application.builder().token(bot_token).build()

    for handler in build_command_handlers(deps):
        app.add_handler(handler)

    return app
