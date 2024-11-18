import sqlite3
from sqlite3 import dbapi2
from typing import Optional
from bson import ObjectId
from pymongo import MongoClient
import mysql.connector
import ssl
import certifi

class DatabaseManager:
    def __init__(self, database_type: str, database_name: str, 
                 mongodb_connection_string: Optional[str] = None,
                 mysql_config: Optional[dict] = None):
        self.database_type = database_type
        self.database_name = database_name

        if database_type == 'sqlite':
            # Cloud SQLite connection string handling
            if self.database_name.startswith('sqlitecloud://'):
                self.connection = self.connect_to_cloud_sqlite(self.database_name)
            else:
                # For local SQLite connections
                self.connection = sqlite3.connect(database_name)
            
            self.cursor = self.connection.cursor()
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    creator_id INTEGER NOT NULL,
                    users TEXT NOT NULL
                )
            """)

            self.connection.commit()

        elif database_type == 'mongodb' and mongodb_connection_string:
            try:
                self.client = MongoClient(
                    mongodb_connection_string,
                    tlsCAFile=certifi.where(),
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                    retryWrites=True,
                    tls=True
                )
                self.client.server_info()  # Test connection
                self.db = self.client[database_name]
                self.collection = self.db["tickets"]
            except Exception as e:
                print(f"MongoDB Connection Error: {str(e)}")
                raise

        elif database_type == 'mysql' and mysql_config:
            self.mysql_connection = mysql.connector.connect(**mysql_config)
            self.mysql_cursor = self.mysql_connection.cursor(dictionary=True)
            self.mysql_cursor.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    creator_id BIGINT NOT NULL,
                    users TEXT NOT NULL
                )
            """)
            self.mysql_connection.commit()

    def connect_to_cloud_sqlite(self, connection_string: str) -> dbapi2.Connection:
        """Connect to a cloud SQLite database."""
        import sqlite3
        import urllib.parse

        # Parse the connection string to get the database details
        parsed_url = urllib.parse.urlparse(connection_string.replace("sqlitecloud://", ""))
        database_url = parsed_url.hostname
        api_key = urllib.parse.parse_qs(parsed_url.query).get('apikey', [None])[0]

        # Ensure API key is present for authentication
        if api_key is None:
            raise ValueError("API key is required for SQLite Cloud connection.")

        # SQLite Cloud uses a specific connection format
        connection = sqlite3.connect(f"file:{database_url}?mode=rwc&cache=shared", uri=True)
        return connection

    async def create_ticket(self, creator_id: int) -> int:
        if self.database_type == 'sqlite':
            self.cursor.execute("INSERT INTO tickets (creator_id, users) VALUES (?, ?)", 
                              (creator_id, str(creator_id)))
            self.connection.commit()
            return self.cursor.lastrowid

        elif self.database_type == 'mongodb':
            try:
                ticket = {"creator_id": creator_id, "users": [creator_id]}
                result = self.collection.insert_one(ticket)
                return result.inserted_id
            except Exception as e:
                print(f"MongoDB Insert Error: {str(e)}")
                raise

        elif self.database_type == 'mysql':
            query = "INSERT INTO tickets (creator_id, users) VALUES (%s, %s)"
            self.mysql_cursor.execute(query, (creator_id, str(creator_id)))
            self.mysql_connection.commit()
            return self.mysql_cursor.lastrowid

    async def add_user_to_ticket(self, ticket_id: int, user_id: int) -> Optional[int]:
        if self.database_type == 'sqlite':
            self.cursor.execute("SELECT users FROM tickets WHERE id = ?", (ticket_id,))
            result = self.cursor.fetchone()
            if result:
                users = result[0].split(',')
                if str(user_id) not in users:
                    users.append(str(user_id))
                    new_users = ','.join(users)
                    self.cursor.execute("UPDATE tickets SET users = ? WHERE id = ?", (new_users, ticket_id))
                    self.connection.commit()
                    return ticket_id

        elif self.database_type == 'mongodb':
            self.collection.update_one({"_id": ticket_id}, {"$addToSet": {"users": user_id}})
            return ticket_id

        elif self.database_type == 'mysql':
            self.mysql_cursor.execute("SELECT users FROM tickets WHERE id = %s", (ticket_id,))
            result = self.mysql_cursor.fetchone()
            if result:
                users = result["users"].split(',')
                if str(user_id) not in users:
                    users.append(str(user_id))
                    new_users = ','.join(users)
                    query = "UPDATE tickets SET users = %s WHERE id = %s"
                    self.mysql_cursor.execute(query, (new_users, ticket_id))
                    self.mysql_connection.commit()
                    return ticket_id

    async def delete_ticket(self, ticket_id):
        if self.database_type == 'sqlite':
            self.cursor.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
            self.connection.commit()

        elif self.database_type == 'mongodb':
            self.collection.delete_one({"_id": ObjectId(ticket_id)})

        elif self.database_type == 'mysql':
            query = "DELETE FROM tickets WHERE id = %s"
            self.mysql_cursor.execute(query, (ticket_id,))
            self.mysql_connection.commit()
