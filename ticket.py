import os
import asyncio
from dotenv import load_dotenv
import nextcord
from nextcord.ext import commands
from pymongo import MongoClient
from bson import ObjectId

# Load environment variables from .env file
load_dotenv()

class TicketBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # MongoDB connection details
        self.mongodb_host = os.getenv("MONGODB_HOST")
        self.mongodb_port = int(os.getenv("MONGODB_PORT", 27018))
        self.mongodb_database = os.getenv("MONGODB_DATABASE")
        self.mongodb_user = os.getenv("MONGODB_USER")
        self.mongodb_password = os.getenv("MONGODB_PASSWORD")

        # Initialize MongoDB client
        self.client = MongoClient(
            f"mongodb://{self.mongodb_user}:{self.mongodb_password}@{self.mongodb_host}:{self.mongodb_port}/{self.mongodb_database}"
        )
        self.db = self.client[self.mongodb_database]
        self.tickets_collection = self.db['tickets']
        self.settings_collection = self.db['settings']

    @nextcord.slash_command(name="setticketcategory", description="Set the category for tickets")
    @commands.has_permissions(administrator=True)
    async def set_ticket_category(self, interaction: nextcord.Interaction, category: nextcord.CategoryChannel):
        """Set the category where tickets will be created"""
        # Update the category ID in the database
        self.settings_collection.update_one(
            {"guild_id": interaction.guild.id},
            {"$set": {"ticket_category_id": category.id}},
            upsert=True
        )
        
        await interaction.response.send_message(f"Ticket category has been set to {category.name}!", ephemeral=True)

    @nextcord.slash_command(name="createticketcategory", description="Create a new category for tickets")
    @commands.has_permissions(administrator=True)
    async def create_ticket_category(self, interaction: nextcord.Interaction, category_name: str = "Tickets"):
        """Create a new category for tickets with a custom name"""
        # Create the category
        category = await interaction.guild.create_category(category_name)
        
        # Update the category ID in the database
        self.settings_collection.update_one(
            {"guild_id": interaction.guild.id},
            {"$set": {"ticket_category_id": category.id}},
            upsert=True
        )
        
        await interaction.response.send_message(f"Created new ticket category: {category_name}", ephemeral=True)

    async def get_or_create_ticket_category(self, guild):
        # First check if we have a stored category ID
        settings = self.settings_collection.find_one({"guild_id": guild.id})
        
        if settings and "ticket_category_id" in settings:
            category = guild.get_channel(settings["ticket_category_id"])
            if category:
                return category

        # If no category exists, create default one
        category = await guild.create_category("Tickets")
        
        # Store the category ID
        self.settings_collection.update_one(
            {"guild_id": guild.id},
            {"$set": {"ticket_category_id": category.id}},
            upsert=True
        )
        
        return category

    @nextcord.slash_command(name="viewticketcategory", description="View the current ticket category")
    @commands.has_permissions(administrator=True)
    async def view_ticket_category(self, interaction: nextcord.Interaction):
        """View the current ticket category settings"""
        settings = self.settings_collection.find_one({"guild_id": interaction.guild.id})
        
        if settings and "ticket_category_id" in settings:
            category = interaction.guild.get_channel(settings["ticket_category_id"])
            if category:
                await interaction.response.send_message(
                    f"Current ticket category: {category.name} (ID: {category.id})",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "The configured ticket category no longer exists! Please set a new one.",
                    ephemeral=True
                )
        else:
            await interaction.response.send_message(
                "No ticket category has been configured yet! Use /setticketcategory or /createticketcategory to set one up.",
                ephemeral=True
            )

    @nextcord.slash_command(name="setup", description="Set up the ticket system")
    @commands.has_permissions(administrator=True)
    async def setup(self, interaction: nextcord.Interaction):
        # Create or get the ticket category
        category = await self.get_or_create_ticket_category(interaction.guild)
        
        embed = nextcord.Embed(
            title="Support Ticket System",
            description="Click the button below to open a ticket:",
            color=nextcord.Color.blue()
        )
        
        view = nextcord.ui.View(timeout=None)
        view.add_item(nextcord.ui.Button(
            style=nextcord.ButtonStyle.primary,
            label="Support Ticket",
            emoji="🎫",
            custom_id="support_ticket"
        ))

        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message(
            f"Ticket system set up successfully in category: {category.name}!",
            ephemeral=True
        )

    @nextcord.slash_command(name="ticket", description="Create a new support ticket")
    async def create_ticket(self, interaction: nextcord.Interaction):
        await self._create_ticket(interaction, "Support")

    async def _create_ticket(self, interaction: nextcord.Interaction, ticket_type: str):
        guild = interaction.guild
        author = interaction.user

        # Get or create the ticket category
        category = await self.get_or_create_ticket_category(guild)

        channel_prefixes = {
            "Support": "support"
        }
        prefix = channel_prefixes.get(ticket_type, "ticket")

        # Create a new ticket in the MongoDB collection
        ticket_id = await self.create_ticket_in_db(author.id)
        channel_name = f"{prefix}-{author.name.lower()}-{ticket_id}"
        
        # Set permissions for the ticket channel
        overwrites = {
            guild.default_role: nextcord.PermissionOverwrite(read_messages=False),
            author: nextcord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: nextcord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        # Create a new text channel for the ticket in the category
        channel = await guild.create_text_channel(
            channel_name,
            overwrites=overwrites,
            category=category,
            topic=f"{ticket_type} ticket for {author.name} (ID: {ticket_id})"
        )

        ticket_emojis = {
            "Support": "🎫"
        }
        emoji = ticket_emojis.get(ticket_type, "🎫")

        # Send a welcome message in the new ticket channel
        await channel.send(f"{emoji} {author.mention} Welcome to your {ticket_type.lower()} ticket (ID: {ticket_id})! Please describe your issue here.")

        # Respond to the interaction to notify the user
        await interaction.response.send_message(f"Ticket created! Please check {channel.mention}", ephemeral=True)

    @nextcord.slash_command(name="close", description="Close the current support ticket")
    async def close_ticket(self, interaction: nextcord.Interaction):
        channel_name = interaction.channel.name
        if not channel_name.startswith(("support-", "bug-", "inquiry-")):
            await interaction.response.send_message("This command can only be used in ticket channels!", ephemeral=True)
            return

        # Extract the ticket ID from the channel name
        ticket_id_str = channel_name.split('-')[-1]
        
        try:
            ticket_id = ObjectId(ticket_id_str)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            return

        # Close the ticket in the MongoDB collection
        await self.delete_ticket_from_db(ticket_id)

        await interaction.response.send_message("Closing this ticket in 5 seconds...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

    @nextcord.slash_command(name="load", description="Load all tickets as channels in the server")
    @commands.has_permissions(administrator=True)
    async def load_tickets(self, interaction: nextcord.Interaction):
        # Get or create the ticket category
        category = await self.get_or_create_ticket_category(interaction.guild)
        
        # Fetch all tickets from the database
        tickets = await self.get_all_tickets()

        if tickets:
            for ticket in tickets:
                creator_id = ticket.get("creator_id")
                ticket_id = str(ticket.get("_id"))

                try:
                    user = await self.bot.fetch_user(creator_id)
                except nextcord.NotFound:
                    continue
                except Exception as e:
                    continue

                overwrites = {
                    interaction.guild.default_role: nextcord.PermissionOverwrite(read_messages=False),
                    user: nextcord.PermissionOverwrite(read_messages=True, send_messages=True),
                    interaction.guild.me: nextcord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
                }

                try:
                    ticket_channel_name = f"ticket-{ticket_id}"
                    ticket_channel = await interaction.guild.create_text_channel(
                        ticket_channel_name,
                        overwrites=overwrites,
                        category=category,
                        topic=f"Ticket for {user.name} (ID: {ticket_id})"
                    )

                    await ticket_channel.send(f"🎫 {user.mention}, this is your support ticket (ID: {ticket_id}). Please describe your issue here.")

                except Exception as e:
                    continue
            
            await interaction.response.send_message("Successfully loaded all tickets as channels.", ephemeral=True)
        else:
            await interaction.response.send_message("No tickets found in the database.", ephemeral=True)

    # [Previous database methods remain the same]
    async def get_all_tickets(self):
        tickets = []
        if self.tickets_collection is not None:
            tickets = list(self.tickets_collection.find())
        return tickets

    async def create_ticket_in_db(self, creator_id: int):
        ticket_data = {
            "creator_id": creator_id,
            "status": "open",
            "users": [creator_id]
        }
        
        result = self.tickets_collection.insert_one(ticket_data)
        return str(result.inserted_id)

    async def delete_ticket_from_db(self, ticket_id: ObjectId):
        result = self.tickets_collection.delete_one({"_id": ticket_id})
        if result.deleted_count == 0:
            print(f"Ticket with ID {ticket_id} not found.")
        else:
            print(f"Ticket with ID {ticket_id} deleted successfully.")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: nextcord.Interaction):
        if interaction.type == nextcord.InteractionType.component:
            custom_id = interaction.data['custom_id']
            if custom_id in ["support_ticket", "bug_report", "other_ticket"]:
                ticket_type = {
                    "support_ticket": "Support",
                    "bug_report": "Bug Report",
                    "other_ticket": "Other"
                }[custom_id]
                await self._create_ticket(interaction, ticket_type)