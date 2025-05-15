import discord
from discord.ext import commands
import os
import json
import logging
import asyncio
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("VanitySniper")

# Load environment variables
load_dotenv()

# Default config structure
default_config = {
    "target_vanity": None,
    "admin_role_id": None,
    "notification_channel_id": None,
    "check_interval": 0.5,  # in seconds
    "guild_id": None
}

class VanitySniper(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(command_prefix="!", intents=intents)
        self.config = self.load_config()
        
    def load_config(self):
        try:
            if os.path.exists('config.json'):
                with open('config.json', 'r') as f:
                    config = json.load(f)
                    # Update with any missing default fields
                    for key, value in default_config.items():
                        if key not in config:
                            config[key] = value
                    return config
            else:
                # Create default config file
                with open('config.json', 'w') as f:
                    json.dump(default_config, f, indent=4)
                return default_config
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return default_config
    
    def save_config(self):
        try:
            with open('config.json', 'w') as f:
                json.dump(self.config, f, indent=4)
            logger.info("Config saved successfully")
        except Exception as e:
            logger.error(f"Error saving config: {e}")
    
    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info("------")
        
        # Load all cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    logger.info(f"Loaded extension: {filename}")
                except Exception as e:
                    logger.error(f"Failed to load extension {filename}: {e}")

    async def setup_hook(self):
        # Any additional setup can go here
        pass

async def main():
    bot = VanitySniper()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.critical("No token found in .env file! Please add your Discord bot token.")
        return
        
    try:
        await bot.start(token)
    except discord.LoginFailure:
        logger.critical("Invalid token! Please check your Discord bot token.")
    except Exception as e:
        logger.critical(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 
