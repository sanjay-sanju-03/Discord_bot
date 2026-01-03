FROM python:3.12-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY discord_bot.py .
COPY .env .env

# Run the bot
CMD ["python", "discord_bot.py"]
