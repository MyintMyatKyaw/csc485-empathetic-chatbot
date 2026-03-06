import os
import json
import re
import traceback
from pathlib import Path
from typing import List, Literal, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from google import genai

# ---------------------------
# Paths
# ---------------------------
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UI_FILE = BASE_DIR / "ui_chatbot.html"

# ---------------------------
# App init (ONLY ONCE)
# ---------------------------
app = FastAPI(title="Empathetic MH Chatbot API")

# Serve static assets: /static/styles.css, /static/app.js
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------
# Config
# ---------------------------
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
if not API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY in .env")

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

client = genai.Client(api_key=API_KEY)

# ---------------------------
# Data Models
# ---------------------------
Role = Literal["user", "assistant"]


class ChatTurn(BaseModel):
    role: Role
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatTurn] = []


class EmotionInsight(BaseModel):
    primary_emotion: str
    secondary_emotion: Optional[str] = None
    intensity: float
    needs: List[str]
    risk_level: str  # "none" | "low" | "medium" | "high"
    explanation: str


class SafetyResult(BaseModel):
    triggered: bool
    type: str  # "none" | "self_harm"
    message: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    emotion: EmotionInsight
    safety: SafetyResult


# ---------------------------
# UI Route
# ---------------------------
@app.get("/", response_class=HTMLResponse)
def serve_ui():
    if not UI_FILE.exists():
        return HTMLResponse(
            "<h2>ui_chatbot.html not found</h2><p>Place ui_chatbot.html next to app.py</p>",
            status_code=500,
        )
    return HTMLResponse(UI_FILE.read_text(encoding="utf-8"))


# ---------------------------
# Safety Check (basic prototype)
# ---------------------------
SELF_HARM_PATTERNS = [
    r"\bkill myself\b",
    r"\bsuicide\b",
    r"\bend my life\b",
    r"\bwant to die\b",
    r"\bself[- ]harm\b",
    r"\bhurt myself\b",
    r"\bcan't go on\b",
    r"\bcant go on\b",
    r"\bcan’t go on\b",
]


def safety_check(text: str) -> SafetyResult:
    t = (text or "").lower()
    for pat in SELF_HARM_PATTERNS:
        if re.search(pat, t):
            return SafetyResult(
                triggered=True,
                type="self_harm",
                message=(
                    "I’m really sorry you’re feeling this way. You deserve support right now.\n\n"
                    "If you’re in immediate danger or might act on these thoughts, please contact local emergency services "
                    "or reach out to someone you trust immediately.\n\n"
                    "If you tell me what country you’re in, I can help you find local crisis/hotline options."
                ),
            )
    return SafetyResult(triggered=False, type="none")


# ---------------------------
# Prompt Helpers
# ---------------------------
def format_history(history: List[ChatTurn], max_turns: int = 8) -> str:
    trimmed = history[-max_turns:]
    lines = []
    for turn in trimmed:
        who = "User" if turn.role == "user" else "Assistant"
        lines.append(f"{who}: {turn.content}")
    return "\n".join(lines).strip()


EMOTION_JSON_SCHEMA = """Return ONLY valid JSON with these keys:
{
  "primary_emotion": string,
  "secondary_emotion": string|null,
  "intensity": number (0.0 to 1.0),
  "needs": array of strings (e.g., ["validation","reassurance","support","rest","clarity","grounding"]),
  "risk_level": string ("none"|"low"|"medium"|"high"),
  "explanation": string (short, 1 sentence)
}
No extra text. No markdown. No code fences.
"""


def build_emotion_prompt(user_message: str, history_text: str) -> str:
    return f"""
You are an emotion-and-needs annotator for a student mental-health support chatbot prototype.
You are NOT diagnosing. You are providing supportive reflection labels.

Conversation so far:
{history_text if history_text else "(no prior context)"}

New user message:
{user_message}

{EMOTION_JSON_SCHEMA}
""".strip()


def build_reply_prompt(user_message: str, history_text: str, emotion: dict) -> str:
    return f"""
You are an empathetic mental-health support chatbot for a student prototype.
You are NOT a doctor. Do NOT diagnose. Do NOT provide medication instructions.
Be warm, emotionally mature, and not robotic. Use at most 1 emoji.

Use these counseling micro-skills in order:
1) Validate the feeling (non-judgmental).
2) Reflect what you heard (emotion + situation).
3) Ask ONE gentle open-ended question.
4) Offer ONE small coping suggestion (optional).

Safety rule:
- If user mentions self-harm intent, encourage seeking professional or emergency help. Do not provide instructions.

Conversation so far:
{history_text if history_text else "(no prior context)"}

Emotion insight (for your guidance):
{json.dumps(emotion, ensure_ascii=False)}

New user message:
{user_message}

Write the assistant reply only (no JSON).
""".strip()


def genai_generate_text(prompt: str) -> str:
    """
    Calls Google GenAI and returns plain text.
    """
    resp = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )
    text = getattr(resp, "text", None)
    if not text:
        raise RuntimeError("Empty response text from model.")
    return text.strip()


# ---------------------------
# API Route
# ---------------------------
@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    # 1) Safety
    safety = safety_check(req.message)
    history_text = format_history(req.history)

    if safety.triggered:
        emotion = EmotionInsight(
            primary_emotion="distress",
            secondary_emotion="crisis",
            intensity=0.95,
            needs=["safety", "support"],
            risk_level="high",
            explanation="Message indicates potential self-harm risk; prioritize safety support.",
        )
        return ChatResponse(reply=safety.message or "Please seek help.", emotion=emotion, safety=safety)

    # 2) Emotion JSON
    try:
        emo_prompt = build_emotion_prompt(req.message, history_text)
        emo_text = genai_generate_text(emo_prompt)

        # Strip ```json fences if they appear
        emo_text_clean = re.sub(r"^```json\s*|\s*```$",
                                "", emo_text, flags=re.IGNORECASE).strip()

        try:

            emo_data = json.loads(emo_text_clean)

        except Exception:
            emo_data = {
                "primary_emotion": "unknown",
                "secondary_emotion": None,
                "intensity": 0.5,
                "needs": ["support"],
                "risk_level": "low",
                "explanation": "Could not parse emotion JSON reliably; using fallback.",
            }

        # Validate / coerce
        try:

            emotion = EmotionInsight(**emo_data)
            
        except Exception:
            emotion = EmotionInsight(
                primary_emotion="unknown",
                secondary_emotion=None,
                intensity=0.5,
                needs=["support"],
                risk_level="low",
                explanation="Emotion fields invalid; using fallback.",
            )
            emo_data = emotion.model_dump()

        # 3) Reply
        reply_prompt = build_reply_prompt(req.message, history_text, emo_data)
        reply_text = genai_generate_text(reply_prompt)

        return ChatResponse(
            reply=reply_text,
            emotion=emotion,
            safety=safety,
        )

    except Exception as e:
        print("ERROR in /api/chat:", repr(e))
        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail="Server error while generating response.")
