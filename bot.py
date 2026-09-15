import discord
from discord.ext import commands
import os
import asyncio
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
AI_API_KEY = os.getenv('AI_API_KEY')
AI_API_URL = os.getenv('AI_API_URL')

# Configure Intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

class JarvisAI:
    """Placeholder class for AI integration logic."""
    def __init__(self, api_key, api_url):
        self.api_key = api_key
        self.api_url = api_url

    async def query(self, prompt):
        """Simulates an API call to the LLM."""
        if not self.api_key or not self.api_url:
            return "Error: API key or URL not configured in environment variables."

        # This is a template for a standard OpenAI-compatible API call
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": prompt}]
        }

        try:
            # Using run_in_executor to prevent blocking the event loop during network I/O
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(self.api_url, json=payload, headers=headers, timeout=10)
            )
            
            if response.status_code == 200:
                data = response.json()
                return data['choices'][0]['message']['content']
            else:
                return f"API Error: {response.status_code} - {response.text}"
        except Exception as e:
            return f"Connection Error: {str(e)}"

jarvis_ai = JarvisAI(AI_API_KEY, AI_API_URL)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    print('------')

@bot.event
async def on_message(message):
    # Don't let the bot respond to itself
    if message.author == bot.user:
        return

    # Respond to direct messages or mentions
    if bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        # Remove the mention from the prompt
        clean_content = message.content.replace(f'<@!{bot.user.id}>', '').replace(f'<@{bot.user.id}>', '').strip()
        
        if not clean_content:
            await message.channel.send("How can I assist you, Jordan?")
            return

        async with message.channel.typing():
            response = await jarvis_ai.query(clean_content)
            
            # Discord has a 2000 character limit per message
            if len(response) > 2000:
                for i in range(0, len(response), 2000):
                    await message.reply(response[i:i+2000])
            else:
                await message.reply(response)

    # Process commands if any are defined
    await bot.process_commands(message)

@bot.command()
async def status(ctx):
    """Checks the bot status."""
    await ctx.send("System Status: Online. All modules functioning within normal parameters.")

if __name__ == '__main__':
    if not DISCORD_TOKEN:
        print("Error: DISCORD_TOKEN not found in environment.")
    else:
        bot.run(DISCORD_TOKEN)