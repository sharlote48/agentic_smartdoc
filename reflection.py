import os
import random
import time
from typing import Any, Dict, List

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, ConfigDict, Field


router = APIRouter(tags=["reflection"])


class ReflectionRequest(BaseModel):
    fields: List[Dict[str, Any]] = Field(description="Requested extraction field definitions")
    previous_extraction: Dict[str, Any] = Field(description="Last extraction output that failed validation")
    validation_feedback: str = Field(min_length=1, description="Validation failure feedback")
    attempt_history: List[Dict[str, Any]] = Field(default_factory=list, description="Previous loop attempts")
    current_instructions: str = Field(min_length=1, description="Current extraction instructions")


class ReflectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    updated_instructions: str


def _create_llm() -> ChatGoogleGenerativeAI:
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY")
    if not api_key:
        raise ValueError("Set GOOGLE_API_KEY or GENAI_API_KEY in environment/.env")

    return ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        temperature=0,
        max_retries=2,
    )


def _invoke_with_retry(llm: ChatGoogleGenerativeAI, messages: List[Any]) -> Any:
    for attempt in range(5):
        try:
            return llm.invoke(messages)
        except Exception:
            if attempt == 4:
                raise
            sleep_time = (2 ** attempt) + random.random()
            time.sleep(sleep_time)


@router.post("/reflect", response_model=ReflectionResponse)
async def reflect(req: ReflectionRequest) -> ReflectionResponse:
    try:
        llm = _create_llm()
        messages = [
            SystemMessage(
                content=(
                    "You are a reflection service in an agentic extraction workflow. "
                    "Rewrite extraction instructions so the next extraction attempt is more likely to pass validation. "
                    "Do not change field names or types. Return only the improved instructions text."
                )
            ),
            HumanMessage(
                content=(
                    "Current extraction instructions:\n"
                    f"{req.current_instructions}\n\n"
                    "Requested fields:\n"
                    f"{req.fields}\n\n"
                    "Previous extraction output:\n"
                    f"{req.previous_extraction}\n\n"
                    "Validation feedback:\n"
                    f"{req.validation_feedback}\n\n"
                    "Attempt history:\n"
                    f"{req.attempt_history}\n\n"
                    "Write revised extraction instructions that address the validation failures."
                )
            ),
        ]

        reflection = _invoke_with_retry(llm, messages)
        updated_instructions = str(reflection.content).strip()

        if not updated_instructions:
            raise ValueError("Reflection model returned empty instructions.")

        return ReflectionResponse(
            model=llm.model,
            updated_instructions=updated_instructions,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reflection failed: {exc}") from exc