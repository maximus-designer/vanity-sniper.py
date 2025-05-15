import discord
from discord.ext import commands, tasks
import logging
import asyncio
import time
import aiohttp
import json
import os
import sys
import traceback

logger = logging.getLogger("VanitySniper.Sniper")

class VanitySniper(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active = False
        self.target_vanity = None
        self.start_time = None
        self.session = None
        self.headers = None
        self.snipe_task = None
        self.successful_snipe = False
        self.stats = {
            "attempts": 0,
            "errors": 0,
            "start_time": None
        }
        # Rate limit tracking
        self.rate_limit_reset = 0
        self.rate_limit_remaining = 0
        self.auto_restart = True
        self.min_check_interval = 0.1  # Minimum time between checks in seconds
        # Data backup task
        self.backup_task = None
    
    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        # Initialize with settings from config
        config = self.bot.config
        if config["target_vanity"]:
            self.target_vanity = config["target_vanity"]
        
        # Start config backup task
        self.backup_task = self.backup_config.start()
        
        # Load state from backup if it exists
        await self.load_state()
        
        # Automatically start sniping if configured
        if config.get("auto_start", False) and config.get("guild_id") and self.target_vanity:
            logger.info("Auto-starting vanity sniper due to config setting")
            await asyncio.sleep(2)  # Brief delay to ensure bot is fully initialized
            self.active = True
            self.snipe_task = asyncio.create_task(self.snipe_vanity())
            
    async def cog_unload(self):
        if self.snipe_task:
            self.snipe_task.cancel()
        
        if self.backup_task:
            self.backup_task.cancel()
        
        # Save state before unloading
        await self.save_state()
        
        if self.session:
            await self.session.close()
    
    async def save_state(self):
        """Save the current state to a backup file"""
        try:
            state = {
                "active": self.active,
                "target_vanity": self.target_vanity,
                "stats": self.stats,
                "auto_restart": self.auto_restart
            }
            
            # Save state to file
            backup_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'vanity_state.json')
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            
            with open(backup_path, 'w') as f:
                json.dump(state, f)
                
            logger.info("Successfully saved vanity sniper state")
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    async def load_state(self):
        """Load state from backup file if it exists"""
        try:
            backup_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'vanity_state.json')
            
            if not os.path.exists(backup_path):
                logger.info("No state backup found, using default settings")
                return
                
            with open(backup_path, 'r') as f:
                state = json.load(f)
            
            # Restore state
            self.target_vanity = state.get("target_vanity", self.target_vanity)
            self.auto_restart = state.get("auto_restart", True)
            
            # Only set active if auto_restart is enabled
            if state.get("active", False) and self.auto_restart:
                self.active = True
            
            logger.info(f"Successfully loaded vanity sniper state: target={self.target_vanity}, active={self.active}")
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
    
    @tasks.loop(minutes=5)
    async def backup_config(self):
        """Periodically backup the sniper state"""
        await self.save_state()
    
    @commands.Cog.listener()
    async def on_ready(self):
        # Set up the headers with the bot token for API requests
        self.headers = {
            "Authorization": f"Bot {self.bot.http.token}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (https://github.com/discord/discord-api-docs, v0.0.0)"
        }
        
        # Auto-restart if configured and not already running
        if self.auto_restart and not self.active and self.target_vanity and self.bot.config.get("guild_id"):
            logger.info("Restarting vanity sniper after bot reconnect")
            self.active = True
            self.successful_snipe = False
            self.stats = {
                "attempts": 0,
                "errors": 0,
                "start_time": time.time()
            }
            self.snipe_task = asyncio.create_task(self.snipe_vanity())
    
    @commands.command(name="help")
    async def _help(self, ctx):
        """Shows help for all vanity sniper commands"""
        embed = discord.Embed(
            title="Vanity Sniper Help",
            description="List of all available commands for the Vanity Sniper bot.",
            color=discord.Color.blue()
        )
        
        # Add command descriptions
        embed.add_field(
            name="v!setvanity <code>",
            value="Set the target vanity URL code to snipe.\n"
                  "Example: `v!setvanity mycoolserver`",
            inline=False
        )
        
        embed.add_field(
            name="v!setnotify",
            value="Set the current channel as the notification channel and register the server for vanity sniping.\n"
                  "Example: `v!setnotify`",
            inline=False
        )
        
        embed.add_field(
            name="v!startsniper",
            value="Start the vanity sniper for the configured vanity code.\n"
                  "Example: `v!startsniper`",
            inline=False
        )
        
        embed.add_field(
            name="v!stopsniper",
            value="Stop the currently running vanity sniper.\n"
                  "Example: `v!stopsniper`",
            inline=False
        )
        
        embed.add_field(
            name="v!setinterval <seconds>",
            value="Set how frequently the bot checks for vanity availability (in seconds).\n"
                  "Example: `v!setinterval 0.5`",
            inline=False
        )
        
        embed.add_field(
            name="v!checkvanity [code]",
            value="Check if a vanity URL is currently available. Uses the target vanity if no code is provided.\n"
                  "Example: `v!checkvanity discord`",
            inline=False
        )
        
        embed.add_field(
            name="v!status",
            value="Show the current status of the vanity sniper.\n"
                  "Example: `v!status`",
            inline=False
        )
        
        embed.add_field(
            name="v!help",
            value="Shows this help message.\n"
                  "Example: `v!help`",
            inline=False
        )
        
        embed.set_footer(text="Vanity Sniper v1.0 | All commands require administrator permissions")
        
        await ctx.send(embed=embed)
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setvanity(self, ctx, vanity_code: str):
        """Set the target vanity URL to snipe"""
        # Validate vanity code (2-15 characters, alphanumeric with optional hyphens)
        if not (2 <= len(vanity_code) <= 15 and all(c.isalnum() or c == '-' for c in vanity_code)):
            return await ctx.send("❌ Invalid vanity code! It must be 2-15 characters, alphanumeric or hyphens.")
        
        self.target_vanity = vanity_code.lower()
        self.bot.config["target_vanity"] = self.target_vanity
        self.bot.save_config()
        
        # Save state after important change
        await self.save_state()
        
        await ctx.send(f"✅ Target vanity URL set to: `{self.target_vanity}`")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setnotify(self, ctx):
        """Set the current channel as the notification channel"""
        self.bot.config["notification_channel_id"] = ctx.channel.id
        self.bot.config["guild_id"] = ctx.guild.id
        self.bot.save_config()
        
        # Save state after important change
        await self.save_state()
        
        await ctx.send(f"✅ This channel has been set as the notification channel.")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def startsniper(self, ctx):
        """Start sniping the target vanity URL"""
        if not self.target_vanity:
            return await ctx.send("❌ No target vanity URL set! Use `v!setvanity` first.")
        
        if not self.bot.config["guild_id"]:
            return await ctx.send("❌ Guild ID not set! Run `v!setnotify` in the server you want to set the vanity for.")
        
        if self.active:
            return await ctx.send("❌ Sniper is already running!")
        
        self.active = True
        self.successful_snipe = False
        self.stats = {
            "attempts": 0,
            "errors": 0,
            "start_time": time.time()
        }
        
        # Enable auto-restart
        self.auto_restart = True
        self.bot.config["auto_start"] = True
        self.bot.save_config()
        
        # Save state after important change
        await self.save_state()
        
        # Start sniping in a non-blocking task
        self.snipe_task = asyncio.create_task(self.snipe_vanity())
        
        await ctx.send(f"✅ Vanity sniper started for code: `{self.target_vanity}`")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def stopsniper(self, ctx):
        """Stop the vanity sniper"""
        if not self.active:
            return await ctx.send("❌ Sniper is not currently running!")
        
        if self.snipe_task:
            self.snipe_task.cancel()
            self.snipe_task = None
        
        self.active = False
        self.auto_restart = False
        self.bot.config["auto_start"] = False
        self.bot.save_config()
        
        # Save state after important change
        await self.save_state()
        
        # Calculate stats
        duration = time.time() - self.stats["start_time"] if self.stats["start_time"] else 0
        
        await ctx.send(f"✅ Vanity sniper stopped.\n"
                     f"Attempts: {self.stats['attempts']}\n"
                     f"Errors: {self.stats['errors']}\n"
                     f"Duration: {duration:.2f} seconds")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setinterval(self, ctx, interval: float):
        """Set the check interval in seconds (minimum 0.1)"""
        if interval < 0.1:
            return await ctx.send("❌ Interval must be at least 0.1 seconds to avoid rate limits.")
        
        self.bot.config["check_interval"] = max(interval, self.min_check_interval)
        self.bot.save_config()
        
        # Save state after important change
        await self.save_state()
        
        await ctx.send(f"✅ Check interval set to: `{self.bot.config['check_interval']}` seconds")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def checkvanity(self, ctx, vanity_code: str = None):
        """Check if a vanity URL is available"""
        code_to_check = vanity_code or self.target_vanity
        
        if not code_to_check:
            return await ctx.send("❌ No vanity code provided or set!")
        
        # Show typing indicator while checking
        async with ctx.typing():
            is_available = await self.check_vanity_availability(code_to_check)
        
        if is_available is None:
            await ctx.send("❌ Failed to check vanity availability due to API error.")
        elif is_available:
            await ctx.send(f"✅ The vanity URL `{code_to_check}` is **available**!")
        else:
            await ctx.send(f"❌ The vanity URL `{code_to_check}` is **not available**.")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def status(self, ctx):
        """Show the current status of the vanity sniper"""
        if not self.target_vanity:
            return await ctx.send("❌ No target vanity URL set.")
        
        embed = discord.Embed(title="Vanity Sniper Status", color=discord.Color.blue())
        embed.add_field(name="Target Vanity", value=f"`{self.target_vanity}`", inline=False)
        embed.add_field(name="Active", value=f"{'✅ Yes' if self.active else '❌ No'}", inline=True)
        embed.add_field(name="Auto-Restart", value=f"{'✅ Yes' if self.auto_restart else '❌ No'}", inline=True)
        
        if self.active:
            duration = time.time() - self.stats["start_time"]
            check_interval = self.bot.config.get("check_interval", 0.5)
            
            embed.add_field(name="Running Time", value=f"{duration:.2f} seconds", inline=True)
            embed.add_field(name="Check Interval", value=f"{check_interval} seconds", inline=True)
            embed.add_field(name="Attempts", value=str(self.stats["attempts"]), inline=True)
            embed.add_field(name="Errors", value=str(self.stats["errors"]), inline=True)
            
            if self.rate_limit_remaining > 0:
                embed.add_field(name="Rate Limit Status", value=f"{self.rate_limit_remaining} requests remaining", inline=False)
        
        guild_id = self.bot.config.get("guild_id")
        if guild_id:
            guild = self.bot.get_guild(guild_id)
            embed.add_field(name="Target Server", value=f"{guild.name if guild else 'Unknown'} (ID: {guild_id})", inline=False)
            
        channel_id = self.bot.config.get("notification_channel_id")
        if channel_id:
            channel = self.bot.get_channel(channel_id)
            embed.add_field(name="Notification Channel", value=f"{channel.mention if channel else 'Unknown'}", inline=False)
            
        embed.set_footer(text=f"Vanity Sniper v1.0 | Type v!help for commands")
        
        await ctx.send(embed=embed)
    
    async def check_vanity_availability(self, vanity_code):
        """Check if a vanity URL is available using the Public Invites API"""
        try:
            # Use cached rate limit info to avoid unnecessary requests
            if time.time() < self.rate_limit_reset and self.rate_limit_remaining <= 0:
                wait_time = self.rate_limit_reset - time.time()
                logger.debug(f"Rate limit active, waiting {wait_time:.2f}s before checking")
                await asyncio.sleep(max(0, wait_time))
            
            # Using the Public Invite API to check if a vanity exists
            async with self.session.get(
                f"https://discord.com/api/v10/invites/{vanity_code}",
                headers=self.headers
            ) as response:
                # Update rate limit tracking
                self.update_rate_limits(response)
                
                # 404 means the invite doesn't exist - which means the vanity is available
                if response.status == 404:
                    logger.info(f"Vanity {vanity_code} is available")
                    return True
                # 200 means the invite exists - the vanity is taken
                elif response.status == 200:
                    logger.debug(f"Vanity {vanity_code} is unavailable")
                    return False
                # 429 means we're rate limited
                elif response.status == 429:
                    retry_after = float(response.headers.get('Retry-After', 1))
                    logger.warning(f"Rate limited during availability check, waiting {retry_after}s")
                    await asyncio.sleep(retry_after)
                    return None
                else:
                    # Other status code means we can't determine
                    logger.error(f"Failed to check vanity availability: {response.status}")
                    return None
                    
        except asyncio.TimeoutError:
            logger.warning("Timeout while checking vanity availability")
            return None
        except Exception as e:
            logger.error(f"Error checking vanity availability: {e}")
            return None
    
    def update_rate_limits(self, response):
        """Update the rate limit tracking from response headers"""
        try:
            if 'X-RateLimit-Remaining' in response.headers:
                self.rate_limit_remaining = int(response.headers.get('X-RateLimit-Remaining', 0))
            
            if 'X-RateLimit-Reset' in response.headers:
                self.rate_limit_reset = float(response.headers.get('X-RateLimit-Reset', 0))
            elif 'Retry-After' in response.headers and response.status == 429:
                self.rate_limit_reset = time.time() + float(response.headers.get('Retry-After', 1))
                self.rate_limit_remaining = 0
        except Exception as e:
            logger.error(f"Error updating rate limits: {e}")
    
    async def attempt_set_vanity(self, guild_id, vanity_code):
        """Try to set the vanity URL for the guild"""
        try:
            # Check rate limits before attempting
            if time.time() < self.rate_limit_reset and self.rate_limit_remaining <= 0:
                wait_time = self.rate_limit_reset - time.time()
                logger.debug(f"Rate limit active, waiting {wait_time:.2f}s before setting vanity")
                return {"success": False, "retry_after": wait_time}
            
            start_time = time.time()
            
            # Make request to update vanity URL
            async with self.session.patch(
                f"https://discord.com/api/v10/guilds/{guild_id}/vanity-url",
                json={"code": vanity_code},
                headers=self.headers,
                timeout=5  # Add timeout to avoid hanging
            ) as response:
                elapsed = (time.time() - start_time) * 1000  # Convert to ms
                
                # Update rate limit tracking
                self.update_rate_limits(response)
                
                # Log response for debugging
                response_text = await response.text()
                logger.debug(f"Set vanity response ({response.status}): {response_text}")
                
                if response.status == 200:
                    # Success!
                    logger.info(f"Successfully set vanity URL to {vanity_code} in {elapsed:.2f}ms")
                    return {"success": True, "elapsed": elapsed}
                
                # Handle rate limits
                elif response.status == 429:
                    retry_after = float(response.headers.get('Retry-After', 1))
                    logger.warning(f"Rate limited, waiting {retry_after}s before retrying")
                    return {"success": False, "retry_after": retry_after}
                
                # URL is taken
                elif response.status == 400:
                    try:
                        error_json = await response.json()
                        if "code" in error_json and error_json.get("code") == 50020:
                            logger.debug(f"Vanity {vanity_code} is still taken")
                            return {"success": False, "reason": "taken"}
                        else:
                            logger.warning(f"Unexpected error when setting vanity: {error_json}")
                            return {"success": False, "reason": "error", "details": error_json}
                    except:
                        return {"success": False, "reason": "error", "details": response_text}
                
                # Other errors
                else:
                    logger.error(f"Error when setting vanity (HTTP {response.status}): {response_text}")
                    return {"success": False, "reason": "error", "status": response.status}
        
        except asyncio.TimeoutError:
            logger.warning("Timeout during vanity set attempt")
            return {"success": False, "reason": "timeout"}     
        except Exception as e:
            logger.error(f"Exception during vanity set attempt: {e}")
            return {"success": False, "reason": "exception", "details": str(e)}
    
    async def verify_vanity_set(self, guild_id):
        """Verify that the vanity URL has been successfully set"""
        try:
            async with self.session.get(
                f"https://discord.com/api/v10/guilds/{guild_id}/vanity-url",
                headers=self.headers,
                timeout=5  # Add timeout to avoid hanging
            ) as response:
                # Update rate limit tracking
                self.update_rate_limits(response)
                
                if response.status == 200:
                    data = await response.json()
                    current_vanity = data.get("code")
                    return current_vanity == self.target_vanity
                return False
        except asyncio.TimeoutError:
            logger.warning("Timeout during vanity verification")
            return False
        except Exception as e:
            logger.error(f"Error verifying vanity: {e}")
            return False
    
    async def adaptive_sleep(self, base_interval):
        """Sleep with adaptive timing based on rate limit status"""
        # If we're close to rate limit, increase sleep time
        if self.rate_limit_remaining <= 5 and self.rate_limit_remaining > 0:
            sleep_time = base_interval * 2
        elif self.rate_limit_remaining == 0:
            sleep_time = max(base_interval, 1)  # At least 1 second if rate limited
        else:
            sleep_time = base_interval
            
        # Ensure minimum delay to prevent hammering the API
        await asyncio.sleep(max(sleep_time, self.min_check_interval))
    
    async def snipe_vanity(self):
        """Main sniping logic - runs in background to continuously try setting the vanity URL"""
        if not self.target_vanity:
            logger.error("No target vanity set for sniping!")
            return
        
        logger.info(f"Starting vanity sniper for code: {self.target_vanity}")
        guild_id = self.bot.config["guild_id"]
        check_interval = self.bot.config.get("check_interval", 0.5)
        consecutive_errors = 0
        
        try:
            while self.active and not self.successful_snipe:
                try:
                    # First check if the vanity is available
                    is_available = await self.check_vanity_availability(self.target_vanity)
                    
                    if is_available is True:
                        logger.info(f"Vanity {self.target_vanity} is available! Attempting to claim...")
                        
                        # Try to set the vanity URL immediately
                        self.stats["attempts"] += 1
                        result = await self.attempt_set_vanity(guild_id, self.target_vanity)
                        
                        if result["success"]:
                            # Verify the change to make absolutely sure
                            if await self.verify_vanity_set(guild_id):
                                self.successful_snipe = True
                                self.active = False
                                
                                # Save state after successful snipe
                                await self.save_state()
                                
                                # Send success notification
                                await self.send_success_notification(result["elapsed"])
                                logger.info(f"Successfully sniped vanity URL: {self.target_vanity}")
                                break
                            else:
                                logger.warning("Vanity appears set but verification failed. Continuing attempts.")
                        
                        # Handle rate limits with exact timing
                        elif "retry_after" in result:
                            retry_after = result["retry_after"]
                            logger.info(f"Rate limited, waiting exactly {retry_after:.2f}s")
                            await asyncio.sleep(retry_after)
                            consecutive_errors = 0  # Reset error counter after controlled wait
                        
                        # If other error, log it and continue
                        else:
                            self.stats["errors"] += 1
                            consecutive_errors += 1
                    
                    elif is_available is False:
                        # Vanity not available, keep checking
                        logger.debug(f"Vanity {self.target_vanity} is not available yet. Checking again soon.")
                        consecutive_errors = 0  # Reset error counter on successful check
                    
                    elif is_available is None:
                        # Error checking availability
                        logger.warning("Error checking vanity availability. Will try again.")
                        self.stats["errors"] += 1
                        consecutive_errors += 1
                    
                    # Periodically update the state (every 50 attempts)
                    if self.stats["attempts"] % 50 == 0:
                        await self.save_state()
                    
                    # Implement exponential backoff for consecutive errors
                    if consecutive_errors > 5:
                        logger.warning(f"Multiple consecutive errors ({consecutive_errors}), increasing wait time")
                        await asyncio.sleep(min(consecutive_errors, 10))  # Cap at 10 seconds
                    else:
                        # Sleep adaptively before next check
                        await self.adaptive_sleep(check_interval)
                
                except asyncio.CancelledError:
                    raise  # Re-raise to handle task cancellation
                except Exception as e:
                    logger.error(f"Unhandled exception in sniper loop: {e}")
                    logger.error(traceback.format_exc())  # Log the full traceback
                    self.stats["errors"] += 1
                    consecutive_errors += 1
                    await asyncio.sleep(1)  # Brief pause after errors
                
        except asyncio.CancelledError:
            logger.info("Sniper task was cancelled")
            # Save state on cancellation
            await self.save_state()
        except Exception as e:
            logger.error(f"Unhandled exception in sniper task: {e}")
            logger.error(traceback.format_exc())  # Log the full traceback
            # Save state after crash
            await self.save_state()
            # Auto-restart if configured
            if self.auto_restart:
                logger.info("Auto-restarting sniper after error")
                await asyncio.sleep(2)
                self.snipe_task = asyncio.create_task(self.snipe_vanity())
    
    async def send_success_notification(self, elapsed_ms):
        """Send notification that the vanity URL was successfully sniped"""
        channel_id = self.bot.config.get("notification_channel_id")
        if not channel_id:
            logger.warning("No notification channel set, can't send success notification")
            return
        
        channel = self.bot.get_channel(channel_id)
        if not channel:
            logger.warning("Could not find notification channel")
            return
        
        embed = discord.Embed(
            title="✅ Vanity URL Sniped!",
            description=f"Successfully sniped the vanity URL: `{self.target_vanity}`",
            color=discord.Color.green()
        )
        embed.add_field(name="Response Time", value=f"{elapsed_ms:.2f}ms", inline=True)
        embed.add_field(name="Total Attempts", value=str(self.stats["attempts"]), inline=True)
        embed.set_footer(text=f"Vanity Sniper • {discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        await channel.send("@everyone", embed=embed)

async def setup(bot):
    await bot.add_cog(VanitySniper(bot)) 
