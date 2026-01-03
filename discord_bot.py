import os
import discord
from discord.ext import commands, tasks
from groq import Groq
from dotenv import load_dotenv
import logging
from collections import defaultdict
from datetime import datetime, timedelta
import re
import random

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Initialize Groq client with explicit proxy settings to avoid Railway compatibility issues
try:
    groq_client = Groq(api_key=GROQ_API_KEY)
except TypeError as e:
    if "proxies" in str(e):
        # Workaround for httpx proxy compatibility issue
        import httpx
        groq_client = Groq(api_key=GROQ_API_KEY, http_client=httpx.Client(proxies=None))
    else:
        raise

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Conversation memory (stores last 10 messages per user)
conversation_history = defaultdict(lambda: [])
MAX_HISTORY = 10
HISTORY_TIMEOUT = 3600  # 1 hour

# Rate limiting
user_cooldowns = {}
COOLDOWN_SECONDS = 2

# Track warned users to avoid spam
warned_users = defaultdict(list)
WARN_COOLDOWN = 300  # 5 minutes between warnings per user

# Christmas-themed system prompt with peace & positivity focus
SYSTEM_PROMPT = """You are NoelBot - Santa's friendliest elf helper! 🎅✨

Your personality:
- You're spreading Christmas cheer and positivity with Ho Ho Ho! energy
- Use festive language with emojis like 🎄 🎅 ❤️ ✨ 🎁 🕊️ ❄️
- Always encourage kindness, respect, and peace
- Spread love, joy, and positive vibes
- Be gentle, warm, understanding, and joyful

Your role:
- Help Code of Eve community members with warmth and support
- Gently remind people to be kind and respectful
- Promote peace, calm, and emotional balance
- Share Christmas spirit and festive joy
- Celebrate New Year with countdown energy
- Listen and provide encouragement

Keep responses under 1500 characters, conversational, and filled with Christmas warmth!"""

# Aggressive/Offensive keywords to detect
AGGRESSIVE_KEYWORDS = [
    'hate', 'stupid', 'dumb', 'idiot', 'loser', 'trash',
    'shut up', 'stfu', 'gtfo', 'noob', 'sucks', 'worst', 
    'pathetic', 'disgusting', 'waste', 'horrible'
]

# Positive response templates for peace intervention
PEACE_MESSAGES = [
    "🎄 Hey everyone! It's Christmas season! Let's be happy, calm, and share love with one another ❤️",
    "✨ Remember, the Christmas spirit thrives in kindness! Let's keep our conversation joyful and respectful 🎅",
    "🎁 Friends, spreading cheer means being nice to each other! Let's spread positivity together ❤️",
    "🎄 In the spirit of Christmas, let's be gentle with our words and kind to one another! 🕊️",
    "✨ The magic of Christmas is in our hearts! Let's fill this chat with love and respect 💚",
    "🌟 Remember, we're all part of the Code of Eve family! Let's treat each other with kindness! 🎅",
]

# Christmas commands
CHRISTMAS_FACTS = [
    "Did you know? Christmas is celebrated by over 2 billion people worldwide! 🎄",
    "Fun fact: The Christmas tree tradition started in Germany! 🌲",
    "Did you know? Rudolph the Red-Nosed Reindeer was created in 1939! 🦌",
    "Christmas fact: The first Christmas card was sent in 1843! 💌",
    "Did you know? Santa's sleigh travels at 650 miles per second! 🚀",
]

GIFT_MESSAGES = [
    "🎁 *gives you a beautifully wrapped gift* Merry Christmas! I hope you have a wonderful day! 🎄",
    "🎁 *slides a gift across the floor* The best gift is friendship and positivity! ❤️",
    "✨ *hands you a magical gift box* May your day be filled with Christmas magic! 🎅",
    "🎁 *decorates with tinsel while handing you a gift* Wishing you joy and cheer! 🎄",
]

CAROL_LINES = [
    "🎵 Jingle bells, jingle bells, jingle all the way! 🎄",
    "🎵 Deck the halls with boughs of holly! 🎶",
    "🎵 We wish you a merry Christmas and a happy new year! 🎄",
    "🎵 Let it snow, let it snow, let it snow! ❄️",
    "🎵 Rockin' around the Christmas tree! 🌲",
]

# New Year countdown
NEW_YEAR_2026 = datetime(2026, 1, 1, 0, 0, 0)

# Daily positivity messages
POSITIVITY_MESSAGES = [
    "🎄 You're doing better than you think! ❤️",
    "🎅 Take a breath. Christmas magic is real ✨",
    "❄️ Be kind. You never know what someone is carrying.",
    "🎁 Every moment is a chance to spread joy!",
    "🕊️ Peace begins with a single kind word.",
    "✨ Your kindness matters more than you know.",
    "🎄 Remember: You're stronger than you think!",
    "❤️ Spread love, even when the world seems cold.",
    "🌟 Make someone smile today - it costs nothing!",
    "🎅 The best gift you can give is being yourself.",
]

# Santa greetings
SANTA_GREETINGS = [
    "🎅 Ho Ho Ho! Merry Christmas! ✨",
    "🎄 Ho Ho Ho! Santa's here to bring cheer! 🎁",
    "🎅 Ho Ho Ho! Let's spread some Christmas magic! ✨",
    "🎄 Ho Ho Ho! Christmas vibes all around! ❤️",
]

def get_new_year_countdown():
    """Calculate time remaining until New Year 2026."""
    now = datetime.now()
    time_left = NEW_YEAR_2026 - now
    
    days = time_left.days
    hours, remainder = divmod(time_left.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    return days, hours, minutes, seconds


def split_message(content: str, max_length: int = 2000) -> list[str]:
    """Split long messages into Discord-friendly chunks."""
    if len(content) <= max_length:
        return [content]
    
    chunks = []
    while content:
        if len(content) <= max_length:
            chunks.append(content)
            break
        
        # Find a good break point (space or newline)
        split_point = max_length
        for i in range(max_length, max(max_length - 100, 0), -1):
            if content[i] in (' ', '\n'):
                split_point = i
                break
        
        chunks.append(content[:split_point].strip())
        content = content[split_point:].strip()
    
    return chunks

def get_conversation_context(user_id: int) -> list[dict]:
    """Get conversation history for a user (without timestamps)."""
    history = conversation_history.get(user_id, [])
    # Return only role and content (remove timestamp for API compatibility)
    return [
        {"role": msg["role"], "content": msg["content"]}
        for msg in history[-MAX_HISTORY:] if history
    ]

def add_to_history(user_id: int, role: str, content: str):
    """Add message to conversation history."""
    conversation_history[user_id].append({
        "role": role,
        "content": content,
        "timestamp": datetime.now()
    })
    
    # Clean up old messages
    conversation_history[user_id] = [
        msg for msg in conversation_history[user_id]
        if (datetime.now() - msg["timestamp"]).total_seconds() < HISTORY_TIMEOUT
    ]

def is_on_cooldown(user_id: int) -> bool:
    """Check if user is on cooldown."""
    if user_id not in user_cooldowns:
        return False
    
    time_diff = (datetime.now() - user_cooldowns[user_id]).total_seconds()
    return time_diff < COOLDOWN_SECONDS

def set_cooldown(user_id: int):
    """Set cooldown for user."""
    user_cooldowns[user_id] = datetime.now()

def detect_aggressive_content(content: str) -> bool:
    """Detect if message contains aggressive/offensive language."""
    content_lower = content.lower()
    
    for keyword in AGGRESSIVE_KEYWORDS:
        if keyword in content_lower:
            return True
    
    # Check for excessive caps (SHOUTING)
    if len(content) > 5:
        caps_ratio = sum(1 for c in content if c.isupper()) / len(content)
        if caps_ratio > 0.7:  # More than 70% caps
            return True
    
    return False

def should_warn_user(user_id: int) -> bool:
    """Check if we should warn this user (avoid spam warnings)."""
    now = datetime.now()
    
    # Clean old warnings
    warned_users[user_id] = [
        timestamp for timestamp in warned_users[user_id]
        if (now - timestamp).total_seconds() < WARN_COOLDOWN
    ]
    
    # Only warn if no recent warnings
    if not warned_users[user_id]:
        warned_users[user_id].append(now)
        return True
    
    return False

@bot.event
async def on_ready():
    """Bot ready event."""
    logger.info(f"✅ Code of Eve Christmas Elf Bot logged in as {bot.user}")
    logger.info(f"🤖 Serving {len(bot.guilds)} guild(s)")
    logger.info(f"📊 Members across all guilds: {sum(g.member_count for g in bot.guilds)}")
    
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="the community with love | !help"
    ))

@bot.event
async def on_message(message: discord.Message):
    """Handle incoming messages with peace detection."""
    # Ignore bot's own messages
    if message.author == bot.user:
        return
    
    # Detect aggressive content and intervene (only in servers, not DMs)
    if isinstance(message.channel, discord.TextChannel) and not message.author.bot and detect_aggressive_content(message.content):
        if should_warn_user(message.author.id):
            warning_msg = random.choice(PEACE_MESSAGES)
            try:
                await message.reply(warning_msg, mention_author=False)
                logger.info(f"⚠️ Peace intervention triggered for {message.author} in {message.guild}")
            except:
                pass
    
    # Process commands
    if not message.author.bot and message.content.startswith(("!", "/")):
        await bot.process_commands(message)
        return
    
    # Check if it's a DM (Direct Message)
    is_dm = isinstance(message.channel, discord.DMChannel)
    
    # Check if bot is mentioned or message is a reply to bot or it's a DM
    if is_dm or bot.user.mentioned_in(message) or (
        message.reference and 
        isinstance(message.reference.resolved, discord.Message) and
        message.reference.resolved.author == bot.user
    ):
        # Check cooldown
        if is_on_cooldown(message.author.id):
            await message.reply(
                "⏱️ I'm processing messages quickly! Please wait a moment.",
                mention_author=False
            )
            return
        
        set_cooldown(message.author.id)
        
        # Get the actual message (remove mention if exists)
        user_prompt = message.content.replace(f"<@{bot.user.id}>", "").strip()
        
        if not user_prompt:
            await message.reply(
                "🎄 Hi there! Ask me anything, and I'll help with Christmas cheer! ✨",
                mention_author=False
            )
            return
        
        # Show typing indicator
        async with message.channel.typing():
            try:
                # Get conversation history
                messages = get_conversation_context(message.author.id)
                messages.append({
                    "role": "user",
                    "content": user_prompt
                })
                
                # Get response from Groq
                completion = groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        *messages
                    ],
                    max_tokens=500
                )
                
                reply = completion.choices[0].message.content
                
                # Add to history
                add_to_history(message.author.id, "user", user_prompt)
                add_to_history(message.author.id, "assistant", reply)
                
                # Split and send response
                reply_chunks = split_message(reply)
                for chunk in reply_chunks:
                    await message.reply(chunk, mention_author=False)
                
                logger.info(f"✅ Response sent to {message.author} in {message.guild}")
                
            except Exception as e:
                logger.error(f"❌ Error processing message: {type(e).__name__}: {e}")
                await message.reply(
                    "⚠️ I encountered an error. Please try again later!",
                    mention_author=False
                )

@bot.command(name="bothelp")
async def help_command(ctx):
    """Show help information."""
    embed = discord.Embed(
        title="� NoelBot_Sanjay - Santa's Helper",
        description="A Christmas companion promoting peace, positivity, and New Year joy!",
        color=discord.Color.red()
    )
    embed.add_field(
        name="💬 How to Chat",
        value=f"• Mention me: <@{bot.user.id}> your question\n"
              "• Reply to my message with follow-ups\n"
              "• I remember our conversation for context!",
        inline=False
    )
    embed.add_field(
        name="🎅 Main Commands",
        value="• `!newyear` - 🎆 New Year countdown (HO HO HO!)\n"
              "• `!hohoho` - 🎅 Santa-style greeting\n"
              "• `!cheer` - ✨ Daily positivity message\n"
              "• `!peace` - 🕊️ Calming message\n"
              "• `!sendgift [@user]` - 🎁 Send virtual gift\n"
              "• `!snow` - ❄️ Snowfall animation",
        inline=False
    )
    embed.add_field(
        name="🎄 Festive Commands",
        value="• `!carol` - 🎵 Christmas carol\n"
              "• `!fact` - 📚 Christmas fact\n"
              "• `!ping` - 🏓 Check bot health\n"
              "• `!clear` - 🗑️ Clear your history\n"
              "• `!bothelp` - 📖 Show this message",
        inline=False
    )
    embed.add_field(
        name="✨ Features",
        value="🎄 **Peace & Positivity Guardian** - Gentle intervention for kindness\n"
              "🎆 **New Year Countdown** - Hype countdown to 2026!\n"
              "💾 **Conversation Memory** - Remember context\n"
              "⚡ **Powered by Groq AI** - Intelligent responses",
        inline=False
    )
    embed.add_field(
        name="❤️ Our Mission",
        value="Spread Christmas cheer, kindness, peace, and positivity throughout Code of Eve!",
        inline=False
    )
    embed.set_footer(text="Ho Ho Ho! Spread love! 🎄✨")
    await ctx.send(embed=embed)

@bot.command(name="ping")
async def ping(ctx):
    """Check bot latency."""
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Latency: `{latency}ms`",
        color=discord.Color.green()
    )
    embed.set_footer(text="Bot is running smoothly! 🎄")
    await ctx.send(embed=embed)

@bot.command(name="clear")
async def clear_history(ctx):
    """Clear conversation history for the user."""
    conversation_history[ctx.author.id] = []
    embed = discord.Embed(
        title="✨ History Cleared",
        description="Your conversation history has been cleared!",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@bot.command(name="carol")
async def carol(ctx):
    """Share a Christmas carol."""
    line = random.choice(CAROL_LINES)
    embed = discord.Embed(
        title="🎵 Christmas Carol",
        description=line,
        color=discord.Color.gold()
    )
    embed.set_footer(text="Merry Christmas! 🎄")
    await ctx.send(embed=embed)

@bot.command(name="fact")
async def fact(ctx):
    """Share a Christmas fact."""
    fact_text = random.choice(CHRISTMAS_FACTS)
    embed = discord.Embed(
        title="📚 Christmas Fact",
        description=fact_text,
        color=discord.Color.green()
    )
    embed.set_footer(text="Learn more about Christmas traditions! 🎄")
    await ctx.send(embed=embed)

@bot.command(name="newyear")
async def newyear(ctx):
    """Show New Year countdown - Ho Ho Ho! 🎆"""
    days, hours, minutes, seconds = get_new_year_countdown()
    
    if days < 0:
        embed = discord.Embed(
            title="🎉 Happy New Year 2026!",
            description="🎆 The new year has arrived! Santa is celebrating! 🎊✨",
            color=discord.Color.gold()
        )
    else:
        countdown_text = f"""
🎄 **Ho Ho Ho!** 🎄

Only **{days}** days, **{hours}** hours, **{minutes}** minutes left until New Year! 🎆

⏳ **Time Until New Year 2026** ⏳
📅 **{days}** days
⏰ **{hours}** hours
⏱️ **{minutes}** minutes
⌛ **{seconds}** seconds

🎅 Let's finish this year with kindness and cheer! ❤️
✨ Every moment brings us closer to a fresh start!
        """
        embed = discord.Embed(
            title="🎆 New Year 2026 Countdown 🎆",
            description=countdown_text,
            color=discord.Color.brand_red()
        )
        embed.set_footer(text="Santa's counting down with you! 🎅")
    
    await ctx.send(embed=embed)

@bot.command(name="hohoho")
async def hohoho(ctx):
    """Santa-style greeting from NoelBot! 🎅"""
    greeting = random.choice(SANTA_GREETINGS)
    embed = discord.Embed(
        description=greeting,
        color=discord.Color.brand_red()
    )
    embed.set_footer(text="Santa approves! 🎄")
    await ctx.send(embed=embed)

@bot.command(name="cheer")
async def cheer(ctx):
    """Get a daily dose of positivity and Christmas cheer! ✨"""
    message = random.choice(POSITIVITY_MESSAGES)
    embed = discord.Embed(
        title="🎄 Daily Christmas Cheer 🎄",
        description=message,
        color=discord.Color.gold()
    )
    embed.set_footer(text="Spread the love! ❤️")
    await ctx.send(embed=embed)

@bot.command(name="peace")
async def peace(ctx):
    """Calming message during heated moments 🕊️"""
    peace_message = random.choice(PEACE_MESSAGES)
    embed = discord.Embed(
        title="🕊️ Let's Take a Moment 🕊️",
        description=peace_message,
        color=discord.Color.blue()
    )
    embed.set_footer(text="Christmas spirit = kindness ❤️")
    await ctx.send(embed=embed)

@bot.command(name="sendgift")
async def gift_command(ctx, user: discord.User = None):
    """Send a virtual Christmas gift! 🎁"""
    gift_emoji = random.choice(["🎁", "🎀", "✨", "🌟", "❤️"])
    
    if user:
        message = f"{ctx.author.mention} sends {gift_emoji} to {user.mention}!\n\nMay your day be filled with Christmas magic! 🎄"
    else:
        message = f"{ctx.author.mention} receives {gift_emoji}!\n\nThe best gift is friendship and positivity! ❤️"
    
    embed = discord.Embed(
        title="🎁 Christmas Gift 🎁",
        description=message,
        color=discord.Color.brand_red()
    )
    await ctx.send(embed=embed)

@bot.command(name="snow")
async def snow(ctx):
    """Watch the snowfall! Let it snow! ❄️"""
    snowfall = "❄️ " * 20 + "\n" * 3 + "❄️ " * 20 + "\n" * 2 + "❄️ " * 20
    embed = discord.Embed(
        title="Let It Snow! ❄️",
        description=snowfall + "\n\n*Beautiful snowflakes falling from the sky...*\n\n🎄 Stay warm and cozy! 🎄",
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors."""
    if isinstance(error, commands.CommandNotFound):
        return
    
    logger.error(f"Command error: {error}")
    await ctx.send(f"⚠️ An error occurred: {error}")

# Run the bot
if __name__ == "__main__":
    try:
        logger.info("🚀 Starting Code of Eve Christmas Elf Bot...")
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")
