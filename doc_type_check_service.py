import os
import random
import time
from base64 import b64encode
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Type

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, ConfigDict, Field, create_model


router = APIRouter(tags=["doc_type_check"])


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


class DocTypeCheckPayload(BaseModel):
	fields: List[ExtractionField] = Field(min_length=1)
	instructions: Optional[str] = Field(
		default=None,
		description="Optional check instructions",
	)
	image_filename: str = Field(default="dummy_invoice.png")


class DocTypeCheckRequest(BaseModel):
	fields: Optional[List[ExtractionField]] = Field(default=None)
	instructions: Optional[str] = Field(
		default=None,
		description="Optional check instructions",
	)
	image_filename: Optional[str] = Field(default=None)
	payload: Optional[DocTypeCheckPayload] = Field(
		default=None,
		description="Optional nested payload schema from parser output",
	)


class DocTypeCheckResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	model: str
	document_type: str


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

	return create_model("DocTypeCheckOutput", **model_fields)


def _create_llm() -> ChatGoogleGenerativeAI:
	load_dotenv()
	api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY")
	if not api_key:
		raise ValueError("Set GOOGLE_API_KEY or GENAI_API_KEY in environment/.env")

	return ChatGoogleGenerativeAI(
		model=os.getenv("GEMINI_MODEL"),
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


@router.post("/check-doc-type", response_model=DocTypeCheckResponse)
def check_document_type(payload: DocTypeCheckRequest) -> DocTypeCheckResponse:
	try:
		if payload.payload is not None:
			use_payload = payload.payload
		else:
			use_payload = DocTypeCheckPayload(
				fields=payload.fields or [],
				instructions=payload.instructions,
				image_filename=payload.image_filename or "dummy_invoice.png",
			)

		if not use_payload.fields:
			# Default field for document type
			use_payload.fields = [
				ExtractionField(
					name="document_type",
					type="string",
					required=True,
					description="Type of document, e.g., invoice, receipt, contract"
				)
			]

		image_path = Path(__file__).parent / (use_payload.image_filename or "dummy_invoice.png")
		if not image_path.exists():
			raise HTTPException(status_code=404, detail=f"Image not found: {use_payload.image_filename}")

		output_schema = _build_dynamic_schema(use_payload.fields)
		llm = _create_llm()
		structured_llm = llm.with_structured_output(output_schema)

		schema_lines = [
			f"- {field.name} ({field.type}) required={field.required}: {field.description}"
			for field in use_payload.fields
		]

		instructions = use_payload.instructions or "Determine the type of document from the image."
		image_b64 = b64encode(image_path.read_bytes()).decode("utf-8")

		messages = [
			SystemMessage(
				content=(
					"You are a document type checker. Determine the document type from the image. "
					"Return only the requested fields."
				)
			),
			HumanMessage(
				content=[
					{
						"type": "text",
						"text": (
							"Determine the document type from the image.\n\n"
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
		extracted_data = extracted.model_dump()
		document_type = extracted_data.get("document_type", "unknown")

		return DocTypeCheckResponse(
			model=llm.model,
			document_type=document_type,
		)
	except HTTPException:
		raise
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Document type check failed: {exc}") from exc


@router.post("/check-doc-type-upload", response_model=DocTypeCheckResponse)
def check_document_type_upload(
	file: UploadFile = File(...),
	fields: Optional[str] = Form(None, description="JSON string of fields"),
	instructions: Optional[str] = Form(None)
) -> DocTypeCheckResponse:
	try:
		# Parse fields if provided
		parsed_fields = []
		if fields:
			import json
			parsed_fields = [ExtractionField(**f) for f in json.loads(fields)]

		if not parsed_fields:
			parsed_fields = [
				ExtractionField(
					name="document_type",
					type="string",
					required=True,
					description="Type of document, e.g., invoice, receipt, contract"
				)
			]

		# Read file content
		file_content = file.file.read()
		image_b64 = b64encode(file_content).decode("utf-8")

		output_schema = _build_dynamic_schema(parsed_fields)
		llm = _create_llm()
		structured_llm = llm.with_structured_output(output_schema)

		schema_lines = [
			f"- {field.name} ({field.type}) required={field.required}: {field.description}"
			for field in parsed_fields
		]

		instr = instructions or "Determine the type of document from the uploaded file."
		messages = [
			SystemMessage(
				content=(
					"You are a document type checker. Determine the document type from the file. "
					"Return only the requested fields."
				)
			),
			HumanMessage(
				content=[
					{
						"type": "text",
						"text": (
							"Determine the document type from the uploaded file.\n\n"
							f"Instructions:\n{instr}\n\n"
							"Fields:\n"
							+ "\n".join(schema_lines)
						),
					},
					{
						"type": "image_url",
						"image_url": f"data:image/{file.content_type.split('/')[-1]};base64,{image_b64}",
					},
				],
			),
		]

		extracted = _invoke_with_retry(structured_llm, messages)
		extracted_data = extracted.model_dump()
		document_type = extracted_data.get("document_type", "unknown")

		return DocTypeCheckResponse(
			model=llm.model,
			document_type=document_type,
		)
	except HTTPException:
		raise
	except ValueError as exc:
		raise HTTPException(status_code=400, detail=str(exc)) from exc
	except Exception as exc:
		raise HTTPException(status_code=500, detail=f"Document type check failed: {exc}") from exc