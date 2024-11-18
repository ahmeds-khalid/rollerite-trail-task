import os
import nextcord
from nextcord.ext import commands
from ticket import TicketBot
from dotenv import load_dotenv

load_dotenv()

intents = nextcord.Intents.default()
intents.typing = False
intents.message_content = True
intents.presences = False
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')

bot.add_cog(TicketBot(bot))
bot.run(os.getenv("DISCORD_BOT_TOKEN"))