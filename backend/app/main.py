from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
load_dotenv()
from contextlib import asynccontextmanager
from app.database import create_db_and_tables
import app.models.schema  # To register models
from app.api.routers import router
import os


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    api_key = os.environ.get("GROQ_API_KEY")
    if api_key:
        masked_key = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
        print(f"STARTUP: GROQ_API_KEY is loaded: {masked_key}")
    else:
        print("STARTUP: GROQ_API_KEY is NOT set!")
    yield

app = FastAPI(title="AgentCI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
