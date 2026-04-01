import os
import random
import time
from base64 import b64encode
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Type

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, ConfigDict, Field, create_model


router = APIRouter(tags=["extraction"])


SUPPORTED_TYPES = {
	"string": str,
	"integer": int,
	"float": float,
	"boolean": bool,
	"list[string]": List[str],
	"list[integer]": List[int],
	"list[float]": List[float],
	"list[boolean]": List[bool],
}


class ExtractionField(BaseModel):
	name: str = Field(min_length=1, description="Output field name")
	type: Literal[
		"string",
		"integer",
		"float",
		"boolean",
		"list[string]",
		"list[integer]",
		"list[float]",
		"list[boolean]",
	]
	description: str = Field(
		default="",
		description="What this field should contain and extraction hints",
	)
	required: bool = Field(
		default=True,
		description="If false, model can return null when value is not found",
	)


class ExtractionRequest(BaseModel):
	document_text: str = Field(min_length=1, description="Document content to parse")
	fields: List[ExtractionField] = Field(min_length=1)
	instructions: Optional[str] = Field(
		default=None,
		description="Optional extraction instructions",
	)


class ExtractionResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	model: str
	extracted_data: Dict[str, Any]


class ImageExtractionRequest(BaseModel):
	fields: List[ExtractionField] = Field(min_length=1)
	instructions: Optional[str] = Field(
		default=None,
		description="Optional extraction instructions",
	)
	image_filename: str = Field(default="dummy_invoice.png")


def _build_dynamic_schema(fields: List[ExtractionField]) -> Type[BaseModel]:
	model_fields: Dict[str, Tuple[Any, Any]] = {}

	for field in fields:
		python_type = SUPPORTED_TYPES[field.type]
		if field.required:
			model_fields[field.name] = (
				python_type,
				Field(description=field.description or f"Extract {field.name}"),
			)
		else:
			model_fields[field.name] = (
				Optional[python_type],
				Field(default=None, description=field.description or f"Extract {field.name}"),
			)

	return create_model("ExtractionOutput", **model_fields)


def _create_llm() -> ChatGoogleGenerativeAI:
	load_dotenv()
	api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY")
	if not api_key:
		raise ValueError("Set GOOGLE_API_KEY or GENAI_API_KEY in environment/.env")

	return ChatGoogleGenerativeAI(
		model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
		temperature=0,
		max_retries=2,
	)


def _invoke_with_retry(structured_llm: Any, messages: List[Any]) -> Any:
	for attempt in range(5):
		try:
			return structured_llm.invoke(messages)
		except Exception:
			if attempt == 4:
				raise
			sleep_time = (2 ** attempt) + random.random()
			time.sleep(sleep_time)


@router.post("/extract", response_model=ExtractionResponse)
def extract_information(payload: ExtractionRequest) -> ExtractionResponse:
	try:
		output_schema = _build_dynamic_schema(payload.fields)
		llm = _create_llm()
		structured_llm = llm.with_structured_output(output_schema)

		schema_lines = [
			f"- {field.name} ({field.type}) required={field.required}: {field.description}"
			for field in payload.fields
		]

		instructions = payload.instructions or "Return only values grounded in the document."
		messages = [
			SystemMessage(
				content=(
					"You are an extraction engine. Extract only requested fields and obey types exactly. "
					"If optional values are missing, return null."
				)
			),
			HumanMessage(
				content=(
					"Extract the following fields from the document.\n\n"
					f"Instructions:\n{instructions}\n\n"
					"Fields:\n"
					+ "\n".join(schema_lines)
					+ "\n\nDocument:\n"
					+ payload.document_text
				)
			),
		]

		extracted = _invoke_with_retry(structured_llm, messages)
		return ExtractionResponse(
			model=llm.model,
			extracted_data=extracted.model_dump(),
		)
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}") from exc


@router.post("/extract-image", response_model=ExtractionResponse)
def extract_information_from_image(payload: ImageExtractionRequest) -> ExtractionResponse:
	try:
		image_path = Path(__file__).parent / payload.image_filename
		if not image_path.exists():
			raise HTTPException(status_code=404, detail=f"Image not found: {payload.image_filename}")

		output_schema = _build_dynamic_schema(payload.fields)
		llm = _create_llm()
		structured_llm = llm.with_structured_output(output_schema)

		schema_lines = [
			f"- {field.name} ({field.type}) required={field.required}: {field.description}"
			for field in payload.fields
		]

		instructions = payload.instructions or "Extract values grounded in the invoice image only."
		image_b64 = b64encode(image_path.read_bytes()).decode("utf-8")

		messages = [
			SystemMessage(
				content=(
					"You are an extraction engine. Extract only requested fields and obey types exactly. "
					"If optional values are missing, return null."
				)
			),
			HumanMessage(
				content=[
					{
						"type": "text",
						"text": (
							"Extract the following fields from the invoice image.\n\n"
							f"Instructions:\n{instructions}\n\n"
							"Fields:\n"
							+ "\n".join(schema_lines)
						),
					},
					{
						"type": "image_url",
						"image_url": f"data:image/png;base64,{image_b64}",
					},
				],
			),
		]

		extracted = _invoke_with_retry(structured_llm, messages)
		return ExtractionResponse(
			model=llm.model,
			extracted_data=extracted.model_dump(),
		)
	except HTTPException:
		raise
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Image extraction failed: {exc}") from exc
