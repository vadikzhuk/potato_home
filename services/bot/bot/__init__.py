"""Telegram bot for the home services. Start: python -m bot.main

  main.py      builds the bot from the parts below
  general.py   /start, /help and the list of services
  access.py    who may talk to the bot, and where
  health.py    /health endpoint for the info screen
  common.py    shared helpers (calling services, time, formatting)
  state.py     what the bot remembers between restarts (data/bot/state.json)
  users/       /user_... commands
  tickets/     /ticket... commands and ticket notifications
  estate/      /estate... commands and the daily digest of homes in Italy
"""
