# agentic_smartdoc

Agentic document processing service built with FastAPI, LangChain, and Gemini. Exposes extraction, validation, and reflection capabilities through a single unified API.

## How it works

The system uses two agents embedded in a modular pipeline:

**Agent 1 — Schema builder (pre-pipeline)**
Runs once at integration setup. Converts a user's natural language description into a structured extraction payload. The generated schema is saved and reused across document runs.

**Agent 2 — Self-correction (in-pipeline)**
Runs on every document. After extraction, it checks which fields failed validation and retries with improved instructions — using the `/reflect` endpoint to rewrite prompts before each retry.


<img width="1440" height="1040" alt="image" src="https://github.com/user-attachments/assets/544c6596-5c76-49ce-877f-ecee77159046" />


## Project structure

```
main.py                         # FastAPI entrypoint — mounts all routers
extraction_service.py           # /extract and /extract-image endpoints
validation_service.py           # /validate endpoint
reflection.py                   # /reflect endpoint
agentic_loop.py                 # Extraction + validation retry loop
agentic_loop_with_reflection.py # Extraction + validation + reflection loop
api_run.py                      # Interactive local runner
natural_language_parser.py      # Converts natural language input to payload schema
payload.json                    # Extraction input payload
validation_payload.json         # Validation rules payload
reflection_payload.json         # Standalone reflection test payload
dummy_invoice.png               # Sample invoice for testing
```

## Setup

**1. Add your API key to `.env`:**

```env
GOOGLE_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

Either `GOOGLE_API_KEY` or `GENAI_API_KEY` is accepted.

**2. Install dependencies:**

```bash
uv sync
```

**3. Start the API:**

```bash
uv run main.py
```

API runs at `http://127.0.0.1:8000`. Swagger UI at `http://127.0.0.1:8000/docs`.

## API endpoints

### `POST /extract`
Extract structured fields from raw text.

```json
{
  "document_text": "Invoice INV-001 ...",
  "instructions": "Extract the requested fields accurately.",
  "fields": [
    { "name": "invoice_number", "type": "string", "required": true, "description": "Invoice ID" }
  ]
}
```

### `POST /extract-image`
Extract structured fields from an image file.

```json
{
  "image_filename": "dummy_invoice.png",
  "instructions": "Extract invoice details accurately.",
  "fields": [
    { "name": "invoice_number", "type": "string", "required": true, "description": "Invoice ID or number" }
  ]
}
```

Supported field types: `string`, `integer`, `float`, `boolean`, `list[string]`, `list[integer]`, `list[float]`, `list[boolean]`

### `POST /validate`
Validate extracted data against a set of rules.

```json
{
  "data": { "currency": "USD", "invoice_date": "2026-03-25", "total_amount": 120.5 },
  "rules": [
    { "field_name": "currency", "rule_type": "enum", "criteria": ["USD", "EUR", "SGD"] }
  ]
}
```

Supported rule types: `enum`, `regex`, `range`, `date`, `type_check`

### `POST /reflect`
Rewrite extraction instructions after a validation failure.

```json
{
  "fields": [...],
  "previous_extraction": {...},
  "validation_feedback": "invoice_date format is inconsistent.",
  "attempt_history": [],
  "current_instructions": "Extract the requested data accurately from the document."
}
```

> Reflection rewrites instructions only — it does not change field names or types.

## Running locally

### Interactive runner

```bash
uv run main.py # to start the server 
uv run api_run.py
```

Available modes: `extraction`, `validation`, `both`, `reflect`, `all`

When running extraction, choose between loading `payload.json` or entering a natural language request (parsed automatically into the correct schema).

`all` runs extraction → validation → reflection in sequence.

### Agentic loop (without reflection)

```bash
uv run agentic_loop.py
```

Flow: extract → validate → rewrite instructions locally → retry until success or max attempts.

### Agentic loop (with reflection)

```bash
uv run agentic_loop_with_reflection.py
```

Flow: extract → validate → call `/reflect` → retry with reflected instructions → repeat until success or max attempts.

## Troubleshooting

**`500` error on extraction**
Usually a Gemini quota issue (`429 RESOURCE_EXHAUSTED`). Wait for quota reset, switch API key, or reduce retry frequency during testing.

**`.env` pushed to git despite `.gitignore`**
The file was tracked before the ignore rule was added. Fix with:

```bash
git rm --cached .env
git commit -m "stop tracking .env"
git push
```

If secrets were ever pushed, rotate them immediately.

## Roadmap

- [ ] Add LLM-as-Judge evaluation
