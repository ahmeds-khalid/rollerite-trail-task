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
        self.mongodb_port = int(os.getenv("MONGODB_PORT", 27018))  # Default MongoDB port is 27017
        self.mongodb_database = os.getenv("MONGODB_DATABASE")
        self.mongodb_user = os.getenv("MONGODB_USER")
        self.mongodb_password = os.getenv("MONGODB_PASSWORD")

        # Initialize MongoDB client
        self.client = MongoClient(
            f"mongodb://{self.mongodb_user}:{self.mongodb_password}@{self.mongodb_host}:{self.mongodb_port}/{self.mongodb_database}"
        )
        self.db = self.client[self.mongodb_database]
        self.tickets_collection = self.db['tickets']

    @nextcord.slash_command(name="setup", description="Set up the ticket system")
    @commands.has_permissions(administrator=True)
    async def setup(self, interaction: nextcord.Interaction):
        embed = nextcord.Embed(title="Support Ticket System", description="Click the button below to open a ticket:", color=nextcord.Color.blue())
        
        view = nextcord.ui.View()
        view.add_item(nextcord.ui.Button(style=nextcord.ButtonStyle.primary, label="Support Ticket", emoji="🎫", custom_id="support_ticket"))

        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("Ticket system set up successfully!", ephemeral=True)

    @nextcord.slash_command(name="ticket", description="Create a new support ticket")
    async def create_ticket(self, interaction: nextcord.Interaction):
        await self._create_ticket(interaction, "Support")

    async def _create_ticket(self, interaction: nextcord.Interaction, ticket_type: str):
        guild = interaction.guild
        author = interaction.user

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

        # Create a new text channel for the ticket
        channel = await guild.create_text_channel(
            channel_name,
            overwrites=overwrites,
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
        
        # Convert the ticket ID to ObjectId (MongoDB format)
        try:
            ticket_id = ObjectId(ticket_id_str)
        except Exception as e:
            await interaction.response.send_message(f"Error: {str(e)}", ephemeral=True)
            return

        # Proceed with closing the ticket in the MongoDB collection
        await self.delete_ticket_from_db(ticket_id)

        # Notify the user that the ticket is being closed
        await interaction.response.send_message("Closing this ticket in 5 seconds...")
        await asyncio.sleep(5)
        
        # Delete the ticket channel
        await interaction.channel.delete()

    @nextcord.slash_command(name="load", description="Load all tickets as channels in the server")
    @commands.has_permissions(administrator=True)
    async def load_tickets(self, interaction: nextcord.Interaction):
        # Fetch all tickets from the database
        tickets = await self.get_all_tickets()

        if tickets:
            # Iterate through the tickets and create a channel for each
            for ticket in tickets:
                creator_id = ticket.get("creator_id")
                ticket_id = str(ticket.get("_id"))

                # Try to fetch the user by creator_id
                try:
                    user = await self.bot.fetch_user(creator_id)
                except nextcord.NotFound:
                    await interaction.response.send_message(f"User with ID {creator_id} not found, skipping ticket {ticket_id}.", ephemeral=True)
                    continue
                except Exception as e:
                    await interaction.response.send_message(f"Error fetching user with ID {creator_id}: {str(e)}", ephemeral=True)
                    continue

                # Set permissions for the ticket channel
                overwrites = {
                    interaction.guild.default_role: nextcord.PermissionOverwrite(read_messages=False),
                    user: nextcord.PermissionOverwrite(read_messages=True, send_messages=True),
                    interaction.guild.me: nextcord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
                }

                # Create the channel for the ticket
                try:
                    ticket_channel_name = f"ticket-{ticket_id}"
                    ticket_channel = await interaction.guild.create_text_channel(
                        ticket_channel_name,
                        overwrites=overwrites,
                        topic=f"Ticket for {user.name} (ID: {ticket_id})"
                    )

                    # Send a welcome message in the new ticket channel
                    await ticket_channel.send(f"🎫 {user.mention}, this is your support ticket (ID: {ticket_id}). Please describe your issue here.")

                    # Log the creation of the ticket channel
                    print(f"Created channel for ticket {ticket_id} ({ticket_channel_name})")

                except Exception as e:
                    await interaction.response.send_message(f"Error creating channel for ticket {ticket_id}: {str(e)}", ephemeral=True)
                    continue
            
            await interaction.response.send_message(f"Successfully loaded all tickets as channels.", ephemeral=True)
        else:
            await interaction.response.send_message("No tickets found in the database.", ephemeral=True)

    async def get_all_tickets(self):
        # Fetch all tickets from the database (MongoDB)
        tickets = []
        if self.tickets_collection is not None:  # Check if the collection exists
            tickets = list(self.tickets_collection.find())
        return tickets

    async def create_ticket_in_db(self, creator_id: int):
        # Insert a new ticket into the MongoDB collection
        ticket_data = {
            "creator_id": creator_id,
            "status": "open",
            "users": [creator_id]
        }
        
        # Insert the ticket and get the result
        result = self.tickets_collection.insert_one(ticket_data)
        
        # Return the ticket's ObjectId as a string
        return str(result.inserted_id)  # No need to await here

    async def delete_ticket_from_db(self, ticket_id: ObjectId):
        # Delete a ticket from the MongoDB collection
        result = self.tickets_collection.delete_one({"_id": ticket_id})
        if result.deleted_count == 0:
            print(f"Ticket with ID {ticket_id} not found.")
        else:
            print(f"Ticket with ID {ticket_id} deleted successfully.")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: nextcord.Interaction):
        # Listen for button interactions to create tickets
        if interaction.type == nextcord.InteractionType.component:
            custom_id = interaction.data['custom_id']
            if custom_id in ["support_ticket", "bug_report", "other_ticket"]:
                ticket_type = {
                    "support_ticket": "Support",
                    "bug_report": "Bug Report",
                    "other_ticket": "Other"
                }[custom_id]
                await self._create_ticket(interaction, ticket_type)
