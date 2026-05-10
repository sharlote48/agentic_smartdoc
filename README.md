# agentic_smartdoc

Agentic document processing service built with FastAPI, LangChain, and Gemini.

This project exposes four API capabilities under one FastAPI app:

1. Extraction
2. Validation
3. Reflection
4. Doc Type Check

The system is designed for invoice-like document workflows where an agent:

1. checks the document type
2. extracts structured fields from an image
3. validates the extracted output against rules
4. reflects on validation failures
5. retries extraction with improved instructions

A browser-based UI (`UI.py`) provides a guided 3-step interface for configuring schemas (via natural language or predefined JSON), selecting pipelines, and running services end-to-end.

## Overview

The main API entrypoint is `main.py`. It mounts four routers into one service:

1. `extraction_service.py`
2. `validation_service.py`
3. `reflection.py`
4. `doc_type_check_service.py`

All routes are served from the same base endpoint, for example:

1. `http://127.0.0.1:8000/extract`
2. `http://127.0.0.1:8000/extract-image`
3. `http://127.0.0.1:8000/validate`
4. `http://127.0.0.1:8000/reflect`
5. `http://127.0.0.1:8000/check-doc-type`

The UI runs as a separate FastAPI app at `http://127.0.0.1:8001/ui`.

## Architecture Diagram

```mermaid
flowchart TD
	A[Browser UI / api_run.py] --> UI[UI.py :8001]
	UI --> B[main.py FastAPI App :8000]
	A --> B

	B --> C[/extract]
	B --> D[/extract-image]
	B --> E[/validate]
	B --> F[/reflect]
	B --> N[/check-doc-type]

	C --> G[extraction_service.py]
	D --> G
	E --> H[validation_service.py]
	F --> I[reflection.py]
	N --> O[doc_type_check_service.py]

	G --> J[Gemini 2.5 Flash]
	I --> J
	O --> J

	K[agentic_loop.py] --> D
	K --> E

	L[agentic_loop_with_reflection.py] --> D
	L --> E
	L --> F

	P[natural_language_parser.py] --> UI
```

## Project Structure

Key files:

1. `main.py`
	 FastAPI app entrypoint that mounts all service routers.

2. `extraction_service.py`
	 Extraction endpoints using Gemini structured output.

3. `validation_service.py`
	 Rule-based validation service.

4. `reflection.py`
	 Reflection service that rewrites extraction instructions after validation failure.

5. `doc_type_check_service.py`
	 Document type detection service. Identifies the document type (invoice, receipt, contract, etc.) from an image using Gemini structured output. Exposes `/check-doc-type` and `/check-doc-type-upload`.

6. `UI.py`
	 Browser-based UI (port 8001). Provides a 3-step guided workflow: select pipeline → configure schema → run services. Supports natural language schema generation, predefined JSON schemas, document upload (drag-and-drop or file path), and consecutive multi-service pipelines.

7. `natural_language_parser.py`
	 Converts natural language descriptions into structured JSON payloads for extraction, validation, or doc type check services using Gemini.

8. `api_run.py`
	 Interactive CLI runner for calling extraction, validation, reflection, doc type check, or combined flows.

9. `agentic_loop.py`
	 Image-only extraction + validation retry loop.

10. `agentic_loop_with_reflection.py`
	 Image-only extraction + validation + reflection retry loop.

11. `payload.json`
	 Extraction input payload.

12. `validation_payload.json`
	 Validation rules and optional standalone validation data.

13. `reflection_payload.json`
	 Standalone reflection request payload.

14. `dummy_invoice.png`
	 Sample invoice image used by extraction and agentic loops.

Example `.env`:

```env
GOOGLE_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

Either `GOOGLE_API_KEY` or `GENAI_API_KEY` is accepted.

## Install Dependencies

If you are using `uv`:

```bash
uv sync
```

## Run The API

Start the unified FastAPI service:

```bash
uv run main.py
```

Start the UI (in a second terminal):

```bash
uv run uvicorn UI:app --host 0.0.0.0 --port 8001 --reload
```

Open the UI at `http://localhost:8001/ui`.

Health endpoint:

```bash
curl http://127.0.0.1:8000/
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

## Browser UI

The UI is a guided 3-step workflow:

### Step 1 — Select Service

Choose from individual or combined pipelines:

| Option | Pipeline |
|---|---|
| Extraction | Extraction |
| Validation | Extraction → Validation → Reflection |
| Doc Type Check | Doc Type Check |
| Doc Check + Extract | Doc Type Check → Extraction |
| Extract + Validate | Extraction → Validation → Reflection |
| All Services | Doc Type Check → Extraction → Validation → Reflection |

### Step 2 — Configure Schema

Choose a schema source:

- **Predefined** — loads `payload.json` and/or `validation_payload.json` for the selected services
- **Natural Language** — describe what to extract or validate in plain text; Gemini generates a combined schema for all selected services

The generated schema is editable before confirming.

### Step 3 — Run Services

Shows the pipeline that will execute. After clicking Run, services are called consecutively and the full response is displayed.

### Document Upload

The left panel accepts a document in two ways:

- **Browse / Drop** — standard file picker or drag-and-drop
- **File Path** — paste an absolute local path

Both methods make the file available to the backend. The preview updates immediately for images; PDFs show a text confirmation.

## API Endpoints

### 1. `POST /extract`

Extracts structured data from raw text.

Request shape:

```json
{
	"document_text": "Invoice INV-001 ...",
	"instructions": "Extract the requested fields accurately.",
	"fields": [
		{
			"name": "invoice_number",
			"type": "string",
			"required": true,
			"description": "Invoice ID"
		}
	]
}
```

### 2. `POST /extract-image`

Extracts structured data from an image file in the repo.

Request shape:

```json
{
	"image_filename": "dummy_invoice.png",
	"instructions": "Extract invoice details accurately.",
	"fields": [
		{
			"name": "invoice_number",
			"type": "string",
			"required": true,
			"description": "Invoice ID or number"
		}
	]
}
```

Supported field types:

1. `string`
2. `integer`
3. `float`
4. `boolean`
5. `list[string]`
6. `list[integer]`
7. `list[float]`
8. `list[boolean]`

Example:

```bash
curl -X POST "http://127.0.0.1:8000/extract-image" \
	-H "Content-Type: application/json" \
	--data @payload.json
```

### 3. `POST /validate`

Validates extracted data using rule objects.

Request shape:

```json
{
	"data": {
		"currency": "USD",
		"invoice_date": "2026-03-25",
		"total_amount": 120.5
	},
	"rules": [
		{
			"field_name": "currency",
			"rule_type": "enum",
			"criteria": ["USD", "EUR", "SGD"]
		}
	]
}
```

Supported rule types:

1. `enum`
2. `regex`
3. `range`
4. `date`
5. `type_check`

Example:

```bash
curl -X POST "http://127.0.0.1:8000/validate" \
	-H "Content-Type: application/json" \
	--data @validation_payload.json
```

### 4. `POST /reflect`

Uses Gemini to rewrite extraction instructions after validation failure.

Request shape:

```json
{
	"fields": [...],
	"previous_extraction": {...},
	"validation_feedback": "invoice_date format is inconsistent.",
	"attempt_history": [],
	"current_instructions": "Extract the requested data accurately from the document."
}
```

Example:

```bash
curl -X POST "http://127.0.0.1:8000/reflect" \
	-H "Content-Type: application/json" \
	--data @reflection_payload.json
```

### 5. `POST /check-doc-type`

Identifies the type of document from an image file in the repo.

Request shape:

```json
{
	"image_filename": "dummy_invoice.png",
	"instructions": "Determine the type of document from the image.",
	"fields": [
		{
			"name": "document_type",
			"type": "string",
			"required": true,
			"description": "Type of document, e.g., invoice, receipt, contract"
		}
	]
}
```

Response shape:

```json
{
	"model": "gemini-2.5-flash-lite",
	"document_type": "invoice"
}
```

### 6. `POST /check-doc-type-upload`

Same as `/check-doc-type` but accepts a multipart file upload instead of a server-side filename.

Example:

```bash
curl -X POST "http://127.0.0.1:8000/check-doc-type-upload" \
	-F "file=@invoice.png" \
	-F 'instructions=Determine the document type'
```

## Payload Files

### `payload.json`

Defines the extraction request used by local runners.

Includes:

1. `image_filename`
2. `instructions`
3. `fields`

### `validation_payload.json`

Defines validation rules.

Includes:

1. `rules`
2. optional `data` for standalone validation-only runs

When running agentic loops, the `data` section is ignored and replaced with live extraction output.

### `reflection_payload.json`

Defines a standalone reflection request for testing `/reflect` directly.

## Local Runner

Use the interactive runner:

```bash
uv run api_run.py
```

When extraction is selected, `api_run.py` gives two input options:

1. Use the existing `payload.json` file
2. Enter a natural language extraction request, which is parsed by `natural_language_parser.py` into the same payload schema

Available modes:

1. extraction
2. validation
3. both
4. reflect
5. all (extraction → validation → reflection)
6. doc_type_check

## Natural Language Parser

`natural_language_parser.py` converts plain-text descriptions into structured service payloads using Gemini.

Supported service types:

1. `extraction` — generates `image_filename`, `instructions`, `fields`
2. `validation` — generates `data`, `rules`
3. `doc_type_check` — generates `image_filename`, `instructions`, `fields`

Used by the UI when the Natural Language schema source is selected, and available as a CLI:

```bash
uv run natural_language_parser.py
```

## Agentic Workflows

### `agentic_loop.py`

Runs an extraction + validation loop.

Flow:

1. call `/extract-image`
2. call `/validate`
3. if invalid, rewrite instructions locally
4. retry until success or max attempts

Run it:

```bash
uv run agentic_loop.py
```

### `agentic_loop_with_reflection.py`

Runs extraction + validation + reflection.

Flow:

1. call `/extract-image`
2. call `/validate`
3. if invalid, call `/reflect`
4. use reflected instructions for next extraction attempt
5. retry until success or max attempts

Run it:

```bash
uv run agentic_loop_with_reflection.py
```

## Gemini Usage

Gemini is currently used in:

1. `extraction_service.py`
2. `reflection.py`
3. `doc_type_check_service.py`
4. `natural_language_parser.py`

Default model:

```text
gemini-2.5-flash
```

You can override it with:

```env
GEMINI_MODEL=gemini-2.5-flash
```

`natural_language_parser.py` uses `gemini-2.5-flash-lite` regardless of this setting.

## Common Issues

### 1. `500 Internal Server Error` on extraction

Often this is an upstream Gemini quota or rate-limit issue.

Typical underlying cause:

1. `429 RESOURCE_EXHAUSTED`

What to do:

1. wait for quota reset
2. switch API key/project
3. enable billing or higher quota
4. reduce repeated retries during testing

### 2. `.env` still gets pushed even though it is in `.gitignore`

That means `.env` was already tracked before the ignore rule applied.

Fix:

```bash
git rm --cached .env
git commit -m "Stop tracking .env"
git push
```

If secrets were ever pushed, rotate them.

### 3. `origin` remote does not exist

Add it:

```bash
git remote add origin https://github.com/<user>/<repo>.git
```

## Example Workflow

1. Put your Gemini API key in `.env`
2. Start the API:

```bash
uv run main.py
```

3. Start the UI (second terminal):

```bash
uv run uvicorn UI:app --host 0.0.0.0 --port 8001 --reload
```

4. Open `http://localhost:8001/ui`, select a pipeline, configure the schema, and run.

Or use the CLI runner:

```bash
uv run api_run.py
```

Or run an agentic loop directly:

```bash
uv run agentic_loop_with_reflection.py
```

## Notes

1. The service is named `document-processing` in the health endpoint because extraction, validation, reflection, and doc type check are all deployed under one FastAPI app.
2. `dummy_invoice.png` is the sample image used by extraction and agentic loop demos.
3. Reflection does not change field names or types. It only rewrites extraction instructions.
4. The UI's Validation pipeline always runs the full Extract → Validate → Reflect sequence, matching the `all` mode in `api_run.py`.

## TODO

- Add LLM-as-Judge as evaluation method
