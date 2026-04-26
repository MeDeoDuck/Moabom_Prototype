"""
Config module - Environment variables and settings
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/techdb")

# API Keys
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
HF_TOKEN = os.getenv("HF_TOKEN", "")

# Server
PORT = int(os.getenv("PORT", 8000))
HOST = "0.0.0.0"
