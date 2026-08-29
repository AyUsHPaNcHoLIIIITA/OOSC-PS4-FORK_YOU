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
    # Report the *resolved* LLM config so a gateway switch is visible at boot.
    # LLM_API_KEY (any OpenAI-compatible gateway) takes precedence over GROQ_API_KEY.
    from app.llm_utils import get_base_url, get_model_name
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY")
    if api_key:
        which = "LLM_API_KEY" if os.environ.get("LLM_API_KEY") else "GROQ_API_KEY"
        masked_key = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
        print(f"STARTUP: {which} is loaded: {masked_key}")
        print(f"STARTUP: LLM endpoint = {get_base_url()} | model = {get_model_name()}")
    else:
        print("STARTUP: No LLM_API_KEY / GROQ_API_KEY set — generation returns MOCK "
              "scenarios and evaluation is NOT run.")
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
