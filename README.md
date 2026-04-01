# agentic_smartdoc

Agentic document processing service built with FastAPI, LangChain, and Gemini.

This project exposes three API capabilities under one FastAPI app:

1. Extraction
2. Validation
3. Reflection

The system is designed for invoice-like document workflows where an agent:

1. extracts structured fields from an image
2. validates the extracted output against rules
3. reflects on validation failures
4. retries extraction with improved instructions

This README documents the document-processing stack only. It intentionally ignores `weather.py`.

## Overview

The main API entrypoint is `main.py`. It mounts three routers into one service:

1. `extraction_service.py`
2. `validation_service.py`
3. `reflection.py`

All routes are served from the same base endpoint, for example:

1. `http://127.0.0.1:8000/extract`
2. `http://127.0.0.1:8000/extract-image`
3. `http://127.0.0.1:8000/validate`
4. `http://127.0.0.1:8000/reflect`

## Architecture Diagram

```mermaid
flowchart TD
	A[Client or Runner] --> B[main.py FastAPI App]
	B --> C[/extract]
	B --> D[/extract-image]
	B --> E[/validate]
	B --> F[/reflect]

	C --> G[extraction_service.py]
	D --> G
	E --> H[validation_service.py]
	F --> I[reflection.py]

	G --> J[Gemini 2.5 Flash]
	I --> J

	K[agentic_loop.py] --> D
	K --> E

	L[agentic_loop_with_reflection.py] --> D
	L --> E
	L --> F

	M[api_run.py] --> B
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

5. `api_run.py`
	 Interactive runner for calling extraction, validation, reflection, or combined flows.

6. `agentic_loop.py`
	 Image-only extraction + validation retry loop.

7. `agentic_loop_with_reflection.py`
	 Image-only extraction + validation + reflection retry loop.

8. `payload.json`
	 Extraction input payload.

9. `validation_payload.json`
	 Validation rules and optional standalone validation data.

10. `reflection_payload.json`
		Standalone reflection request payload.

11. `dummy_invoice.png`
		Sample invoice image used by extraction and agentic loops.

## Requirements

1. Python 3.11+
2. `uv` installed
3. Gemini API key in `.env`

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

Health endpoint:

```bash
curl http://127.0.0.1:8000/
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

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

Available modes:

1. extraction
2. validation
3. both
4. reflect
5. all

`all` runs:

1. extraction
2. validation
3. reflection

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

Default model:

```text
gemini-2.5-flash
```

You can override it with:

```env
GEMINI_MODEL=gemini-2.5-flash
```

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
2. Start API:

```bash
uv run main.py
```

3. Run direct service tests:

```bash
uv run api_run.py
```

4. Run agentic loop without reflection:

```bash
uv run agentic_loop.py
```

5. Run agentic loop with reflection:

```bash
uv run agentic_loop_with_reflection.py
```

## Notes

1. The service is named `document-processing` in the health endpoint because extraction, validation, and reflection are deployed under one FastAPI app.
2. `dummy_invoice.png` is the sample image used by extraction and agentic loop demos.
3. Reflection does not change field names or types. It only rewrites extraction instructions.