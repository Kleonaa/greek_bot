# Greek Bot

A Telegram bot for studying Greek vocabulary with spaced repetition and generated examples.

## Railway deployment

1. Push this repository to GitHub.
2. Create a new Railway project from the GitHub repository.
3. Add a volume and mount it at:

   ```text
   /data
   ```

4. Add these Railway variables:

   ```text
   TELEGRAM_TOKEN=your_telegram_bot_token
   OPENAI_API_KEY=your_openai_api_key
   DB_PATH=/data/greek.db
   ```

5. The start command is already set in `railway.json`:

   ```text
   python3 bot.py
   ```

Railway should then run the bot as a long-lived worker. The SQLite database is stored on the `/data` volume, so generated examples and study progress survive restarts and redeploys.

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 bot.py
```
