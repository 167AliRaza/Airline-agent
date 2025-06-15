from pymongo import MongoClient # type: ignore
from dotenv import load_dotenv
import os
load_dotenv()

def get_db_client():
    try:
        client = MongoClient(os.getenv("DB_URI"))
        return client
    except Exception as e:
        print(f"Error connecting to the database: {e}")
        return None