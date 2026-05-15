from pathlib import Path
import json
import requests
import asyncio
from typing import Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from natural_language_parser import parse_natural_language_to_payload
from agentic_loop_with_reflection import universal_agent_loop


app = FastAPI(
    title="Document Processing UI",
    description="UI client for the document extraction API",
    version="2.0.0",
)

EXTRACTION_PAYLOAD_PATH = Path(__file__).with_name("payload.json")
VALIDATION_PAYLOAD_PATH = Path(__file__).with_name("validation_payload.json")
BASE_API_URL = "http://127.0.0.1:8000"


@app.get("/")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "extraction-ui"}


@app.get("/assets/{filename}")
def get_asset(filename: str) -> FileResponse:
    file_path = Path(__file__).parent / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"{filename} not found")
    return FileResponse(file_path)


class UploadDocumentRequest(BaseModel):
    filepath: str


@app.post("/upload-document")
def upload_document(request: UploadDocumentRequest):
    import shutil
    src = Path(request.filepath).expanduser().resolve()
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {request.filepath}")
    if src.suffix.lower() not in (".png", ".jpg", ".jpeg", ".pdf"):
        raise HTTPException(status_code=400, detail="Only PNG, JPG, and PDF files are supported")
    dest = Path(__file__).parent / src.name
    shutil.copy2(src, dest)
    return {"filename": src.name, "url": f"/assets/{src.name}"}


@app.post("/upload-file")
async def upload_file(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".pdf"):
        raise HTTPException(status_code=400, detail="Only PNG, JPG, and PDF files are supported")
    dest = Path(__file__).parent / file.filename
    dest.write_bytes(await file.read())
    return {"filename": file.filename, "url": f"/assets/{file.filename}"}


class ParseRequest(BaseModel):
    natural_language: str
    service_types: list[str]


@app.post("/parse")
def parse_nl_to_schema(request: ParseRequest):
    try:
        schemas: dict = {}
        for svc in request.service_types:
            schemas[svc] = parse_natural_language_to_payload(request.natural_language, svc)
        return {"schemas": schemas}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PredefinedRequest(BaseModel):
    service_types: list[str]


@app.post("/predefined-schema")
def get_predefined_schema(request: PredefinedRequest):
    try:
        schemas: dict = {}
        for svc in request.service_types:
            if svc == "extraction":
                if not EXTRACTION_PAYLOAD_PATH.exists():
                    raise HTTPException(status_code=404, detail="payload.json not found")
                schemas["extraction"] = json.loads(EXTRACTION_PAYLOAD_PATH.read_text())
            elif svc == "validation":
                if not VALIDATION_PAYLOAD_PATH.exists():
                    raise HTTPException(status_code=404, detail="validation_payload.json not found")
                schemas["validation"] = json.loads(VALIDATION_PAYLOAD_PATH.read_text())
            elif svc == "doc_type_check":
                schemas["doc_type_check"] = {
                    "image_filename": "dummy_invoice.png",
                    "instructions": "Determine the type of document from the image.",
                    "fields": [
                        {
                            "name": "document_type",
                            "type": "string",
                            "required": True,
                            "description": "Type of document, e.g., invoice, receipt, contract",
                        }
                    ],
                }
        return {"schemas": schemas}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CallAPIRequest(BaseModel):
    pipeline: str
    schemas: dict


@app.post("/call-api")
def call_api(request: CallAPIRequest):
    try:
        pipeline = request.pipeline
        schemas = request.schemas
        results: dict = {}
        logs: list = []

        extraction_payload = schemas.get("extraction", {})

        # Doc type check step
        if pipeline in ("doc_type_check", "doc_type_check_extraction", "all"):
            logs.append("[1/4] 🔍 Starting Doc Type Check...")
            doc_payload = schemas.get("doc_type_check", {})
            response = requests.post(f"{BASE_API_URL}/check-doc-type", json=doc_payload, timeout=120)
            if not response.ok:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            results["doc_type_check"] = response.json()

        # Extraction step
        extracted_data: dict = {}
        if pipeline in ("extraction", "doc_type_check_extraction", "extraction_validation_reflect", "all"):
            response = requests.post(f"{BASE_API_URL}/extract-image", json=extraction_payload, timeout=120)
            if not response.ok:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            extraction_result = response.json()
            results["extraction"] = extraction_result
            extracted_data = extraction_result.get("extracted_data", {})

        # Validation + reflect step (option 5 logic from api_run.py)
        if pipeline in ("extraction_validation_reflect", "all"):
            validation_schema = schemas.get("validation", {})
            validation_request = {
                "data": extracted_data,
                "rules": validation_schema.get("rules", []),
            }
            response = requests.post(f"{BASE_API_URL}/validate", json=validation_request, timeout=120)
            if not response.ok:
                raise HTTPException(status_code=response.status_code, detail=response.text)
            validation_result = response.json()
            results["validation"] = validation_result

            reflection_payload = {
                "fields": extraction_payload.get("fields", []),
                "previous_extraction": extracted_data,
                "validation_feedback": validation_result.get(
                    "feedback", "No validation feedback provided."
                ),
                "attempt_history": [
                    {
                        "attempt": 1,
                        "extracted_data": extracted_data,
                        "feedback": validation_result.get("feedback", "No feedback"),
                    }
                ],
                "current_instructions": extraction_payload.get(
                    "instructions",
                    "Extract the requested data accurately from the document.",
                ),
            }
            try:
                # Run agentic loop with reflection (max_attempts=2)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                reflection_result = loop.run_until_complete(
                    universal_agent_loop(
                        extraction_fields=extraction_payload.get("fields", []),
                        validation_rules=validation_schema.get("rules", []),
                        image_filename=extraction_payload.get("image_filename", "dummy_invoice.png"),
                        base_url=BASE_API_URL,
                        max_attempts=3,
                    )
                )
                loop.close()
                results["reflection"] = reflection_result
            except Exception as e:
                results["reflection"] = {"error": f"Reflection step failed: {str(e)}"}

        return results
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect to API: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ui", response_class=HTMLResponse)
def extraction_ui() -> HTMLResponse:
    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Agentic SmartDoc</title>
  <style>
    :root {
      --bg: #f3efe8;
      --panel: #fffaf2;
      --ink: #1d2b36;
      --muted: #6b7680;
      --accent: #005f73;
      --accent-light: #0a9396;
      --accent-2: #ee9b00;
      --border: #d8cec0;
      --success: #2d6a4f;
      --error: #9b2226;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 10% 20%, #fff6df, transparent 28%),
        radial-gradient(circle at 85% 80%, #d4ecef, transparent 28%),
        var(--bg);
      min-height: 100vh;
      padding: 24px;
    }
    .page-title {
      text-align: center;
      font-size: 1.5rem;
      font-weight: 800;
      letter-spacing: 0.01em;
      margin-bottom: 20px;
      color: var(--accent);
    }
    .wrap {
      max-width: 1200px;
      margin: 0 auto;
      display: grid;
      grid-template-columns: 300px 1fr;
      gap: 20px;
      align-items: start;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px;
      box-shadow: 0 8px 20px rgba(0,0,0,.05);
    }
    /* Left panel */
    .left-panel { display: flex; flex-direction: column; gap: 16px; }

    .section-title {
      font-size: 0.9rem;
      font-weight: 700;
      margin-bottom: 10px;
      color: var(--ink);
    }
    .upload-area {
      border: 2px dashed var(--border);
      border-radius: 10px;
      padding: 18px 12px;
      text-align: center;
      cursor: pointer;
      transition: border-color 0.2s, background 0.2s;
      margin-bottom: 0;
    }
    .upload-area:hover, .upload-area.drag-over {
      border-color: var(--accent);
      background: rgba(0,95,115,0.04);
    }
    .upload-icon { font-size: 1.6rem; margin-bottom: 4px; color: var(--muted); }
    .upload-hint { font-size: 0.8rem; color: var(--muted); line-height: 1.5; }
    .upload-hint b { color: var(--accent); cursor: pointer; }
    #fileInput { display: none; }
    .path-row { display: flex; gap: 8px; }
    .path-row input { flex: 1; margin: 0; }
    .path-row .btn { width: auto; padding: 8px 16px; white-space: nowrap; margin: 0; }
    #docPreview {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: white;
      object-fit: contain;
      max-height: 500px;
      display: block;
      cursor: pointer;
      transition: transform 0.2s, box-shadow 0.2s;
    }
    #docPreview:hover {
      transform: scale(1.02);
      box-shadow: 0 8px 24px rgba(0,95,115,0.15);
    }
    .modal {
      display: none;
      position: fixed;
      z-index: 1000;
      left: 0;
      top: 0;
      width: 100%;
      height: 100%;
      background-color: rgba(0,0,0,0.6);
      animation: fadeIn 0.2s ease-in;
    }
    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }
    .modal.show { display: flex; }
    .modal-content {
      margin: auto;
      max-width: 90vw;
      max-height: 90vh;
      object-fit: contain;
    }
    .modal-close {
      position: absolute;
      top: 20px;
      right: 30px;
      font-size: 28px;
      font-weight: bold;
      color: white;
      cursor: pointer;
      transition: color 0.2s;
    }
    .modal-close:hover { color: #ccc; }
    /* Right panel */
    .right-panel { display: flex; flex-direction: column; gap: 16px; }

    /* Step cards */
    .step-card { position: relative; transition: opacity 0.2s; }
    .step-card.locked { opacity: 0.45; pointer-events: none; }

    .step-header {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 14px;
    }
    .step-num {
      width: 26px; height: 26px;
      border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      font-weight: 700; font-size: 0.8rem;
      flex-shrink: 0;
      background: var(--accent);
      color: white;
      transition: background 0.2s;
    }
    .step-num.done { background: var(--success); }
    .step-header h2 { font-size: 1rem; font-weight: 700; flex: 1; }
    .done-chip {
      font-size: 0.75rem;
      font-weight: 600;
      color: var(--success);
      background: rgba(45,106,79,0.1);
      border-radius: 20px;
      padding: 2px 9px;
      display: none;
    }

    /* Service options */
    .group-label {
      font-size: 0.7rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: var(--muted);
      margin: 0 0 7px;
    }
    .service-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin-bottom: 12px;
    }
    .svc-opt {
      border: 2px solid var(--border);
      border-radius: 10px;
      padding: 10px 8px;
      cursor: pointer;
      transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
      background: white;
      user-select: none;
      text-align: center;
    }
    .svc-opt:hover { border-color: var(--accent-light); background: rgba(10,147,150,0.04); }
    .svc-opt.selected {
      border-color: var(--accent);
      background: linear-gradient(135deg, #e3f5f7, #f0fafb);
      box-shadow: 0 0 0 3px rgba(0,95,115,0.14);
    }
    .svc-name { font-weight: 700; font-size: 0.8rem; line-height: 1.3; margin-bottom: 3px; }
    .svc-desc { font-size: 0.68rem; color: var(--muted); line-height: 1.35; }

    /* Tabs */
    .tab-row {
      display: flex;
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      margin-bottom: 14px;
    }
    .tab-btn {
      flex: 1;
      padding: 8px;
      border: none;
      background: white;
      cursor: pointer;
      font-weight: 600;
      font-size: 0.82rem;
      color: var(--muted);
      transition: background 0.15s, color 0.15s;
    }
    .tab-btn + .tab-btn { border-left: 1px solid var(--border); }
    .tab-btn.active { background: var(--accent); color: white; }

    /* Form elements */
    label { display: block; font-weight: 600; font-size: 0.85rem; margin-bottom: 5px; }
    textarea {
      width: 100%;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 9px 11px;
      background: #fff;
      color: var(--ink);
      font-size: 0.85rem;
      margin-bottom: 10px;
      resize: vertical;
      font-family: inherit;
    }
    #nlInput { min-height: 70px; }
    #schemaEdit {
      min-height: 210px;
      font-family: ui-monospace, "Cascadia Code", monospace;
      font-size: 0.78rem;
      line-height: 1.5;
    }
    .hint { font-size: 0.78rem; color: var(--muted); margin: -6px 0 10px; line-height: 1.4; }

    /* Buttons */
    .btn {
      border: none;
      border-radius: 10px;
      font-weight: 700;
      padding: 9px 14px;
      cursor: pointer;
      font-size: 0.88rem;
      transition: filter 0.15s;
      width: 100%;
      display: block;
      margin-bottom: 8px;
    }
    .btn:hover:not(:disabled) { filter: brightness(1.06); }
    .btn:disabled { opacity: 0.4; cursor: not-allowed; filter: none; }
    .btn-primary { background: linear-gradient(90deg, var(--accent), var(--accent-light)); color: white; }
    .btn-success { background: linear-gradient(90deg, var(--success), #40916c); color: white; }
    .btn-outline {
      background: white;
      border: 2px solid var(--accent);
      color: var(--accent);
      font-weight: 700;
    }
    .btn-run {
      background: linear-gradient(90deg, #ae2012, #ca6702);
      color: white;
      font-size: 0.95rem;
      padding: 11px 14px;
    }

    /* Status */
    .status {
      font-size: 0.82rem;
      font-weight: 600;
      min-height: 18px;
      margin: 4px 0 8px;
    }
    .status.ok { color: var(--success); }
    .status.err { color: var(--error); }
    .status.info { color: var(--accent-2); }

    /* Pipeline badge */
    .pipeline-box {
      background: rgba(0,95,115,0.07);
      border: 1px solid rgba(0,95,115,0.18);
      border-radius: 10px;
      padding: 10px 13px;
      margin-bottom: 12px;
    }
    .pipeline-box .pl-label { font-size: 0.75rem; font-weight: 700; color: var(--accent); margin-bottom: 6px; }
    .pl-steps { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .pl-step {
      background: var(--accent);
      color: white;
      border-radius: 6px;
      padding: 3px 10px;
      font-size: 0.75rem;
      font-weight: 700;
    }
    .pl-arrow { color: var(--muted); font-size: 0.85rem; }

    /* Response */
    .response-wrap { margin-top: 10px; }
    .response-box {
      background: #102331;
      color: #d7ebf4;
      border-radius: 10px;
      padding: 12px;
      min-height: 120px;
      font-family: ui-monospace, "Cascadia Code", monospace;
      font-size: 0.76rem;
      white-space: pre-wrap;
      word-break: break-word;
      overflow: auto;
      max-height: 450px;
    }

    /* Results table */
    .results-section-title {
      font-size: 0.85rem;
      font-weight: 700;
      margin-bottom: 10px;
      color: var(--ink);
    }
    .results-summary {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }
    .summary-chip {
      background: rgba(0,95,115,0.08);
      border: 1px solid rgba(0,95,115,0.2);
      border-radius: 8px;
      padding: 8px 14px;
    }
    .summary-chip-label {
      font-size: 0.68rem;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 2px;
    }
    .summary-chip-value { font-weight: 700; color: var(--accent); }
    .status-badge {
      display: inline-block;
      padding: 3px 10px;
      border-radius: 20px;
      font-weight: 700;
      font-size: 0.75rem;
    }
    .status-badge.valid { background: rgba(45,106,79,0.12); color: var(--success); }
    .status-badge.invalid { background: rgba(155,34,38,0.12); color: var(--error); }
    .validation-feedback {
      background: rgba(155,34,38,0.07);
      border: 1px solid rgba(155,34,38,0.2);
      border-radius: 8px;
      padding: 10px 14px;
      margin-bottom: 14px;
      font-size: 0.83rem;
      color: var(--error);
    }
    .results-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.85rem;
      border-radius: 10px;
      overflow: hidden;
      border: 1px solid var(--border);
    }
    .results-table th {
      background: var(--accent);
      color: white;
      padding: 10px 14px;
      text-align: left;
      font-weight: 700;
      font-size: 0.8rem;
    }
    .results-table td {
      padding: 9px 14px;
      border-bottom: 1px solid var(--border);
      vertical-align: top;
    }
    .results-table tr:last-child td { border-bottom: none; }
    .results-table tr:nth-child(even) td { background: rgba(0,95,115,0.03); }
    .results-table .field-name { font-weight: 600; color: var(--ink); white-space: nowrap; }

    @media (max-width: 860px) {
      .wrap { grid-template-columns: 1fr; }
    }
    @media (max-width: 560px) {
      .service-grid { grid-template-columns: 1fr 1fr; }
    }
  </style>
</head>
<body>

<h1 class="page-title">Agentic SmartDoc</h1>

<div class="wrap">

  <!-- ===== LEFT: Upload + Preview ===== -->
  <div class="left-panel">

    <section class="card">
      <p class="section-title">Document</p>
      <div class="tab-row" style="margin-bottom:12px">
        <button class="tab-btn active" id="tabUpload">Browse / Drop</button>
        <button class="tab-btn" id="tabPath">File Path</button>
      </div>

      <div id="uploadSection">
        <div class="upload-area" id="uploadArea">
          <div class="upload-icon">&#128206;</div>
          <div class="upload-hint">Drop file here or <b id="browseBtn">browse</b><br>PNG, JPG or PDF</div>
        </div>
        <input type="file" id="fileInput" accept=".png,.jpg,.jpeg,.pdf" />
      </div>

      <div id="pathSection" style="display:none">
        <div class="path-row">
          <input type="text" id="docPath" placeholder="/path/to/invoice.png" />
          <button class="btn btn-outline" id="loadDocBtn">Load</button>
        </div>
      </div>

      <div class="status" id="docStatus" style="margin-top:8px"></div>
    </section>

    <section class="card">
      <p class="section-title">Document Preview</p>
      <img id="docPreview" src="/assets/dummy_invoice.png" alt="Document preview" />
      <p id="pdfNote" class="hint" style="display:none;margin-top:8px"></p>
      <p class="hint" style="margin-top:8px;margin-bottom:0">Click image to expand &#8599;</p>
    </section>

    <div class="modal" id="imageModal">
      <span class="modal-close" id="closeModal">&times;</span>
      <img class="modal-content" id="modalImage" src="" alt="Full size preview" />
    </div>

  </div>

  <!-- ===== RIGHT: 3-step workflow ===== -->
  <div class="right-panel">

    <!-- ── Step 1: Select Service ── -->
    <section class="card step-card" id="step1Card">
      <div class="step-header">
        <div class="step-num" id="num1">1</div>
        <h2>Select Service</h2>
        <span class="done-chip" id="chip1">&#10003; Done</span>
      </div>

      <p class="group-label">Individual Services</p>
      <div class="service-grid" id="indGrid"></div>

      <p class="group-label">Combined Services</p>
      <div class="service-grid" id="comGrid"></div>

      <button class="btn btn-primary" id="step1Btn" disabled>Continue &#8594;</button>
    </section>

    <!-- ── Step 2: Configure Schema ── -->
    <section class="card step-card locked" id="step2Card">
      <div class="step-header">
        <div class="step-num" id="num2">2</div>
        <h2>Configure Schema</h2>
        <span class="done-chip" id="chip2">&#10003; Done</span>
      </div>

      <div class="tab-row">
        <button class="tab-btn active" id="tabPre">Predefined Schema</button>
        <button class="tab-btn" id="tabNL">Natural Language</button>
        <button class="tab-btn" id="tabManual">Manual Input</button>
      </div>

      <div id="preSection">
        <p class="hint">Load the pre-defined schema from <code>payload.json</code> (and <code>validation_payload.json</code> if validation is selected).</p>
        <button class="btn btn-outline" id="loadPreBtn">Load Predefined Schema</button>
      </div>

      <div id="nlSection" style="display:none">
        <label for="nlInput">Describe what to process</label>
        <textarea id="nlInput" placeholder="e.g. Extract invoice number, vendor name, total amount. Validate that currency is USD or EUR and total_amount is between 0 and 10000."></textarea>
        <button class="btn btn-outline" id="parseBtn">Parse to Schema</button>
      </div>

      <div id="manualSection" style="display:none">
        <label for="manualInput">Paste your schema JSON</label>
        <p class="hint">Paste a schema object directly, e.g. <code>{"extraction": {...}}</code> or <code>{"validation": {...}}</code>.</p>
        <textarea id="manualInput" style="min-height:160px;font-family:ui-monospace,'Cascadia Code',monospace;font-size:0.78rem;line-height:1.5;" placeholder='{"extraction": {"image_filename": "dummy_invoice.png", "fields": [...]}}'></textarea>
        <button class="btn btn-outline" id="loadManualBtn">Load Schema</button>
      </div>

      <div class="status info" id="schemaStatus"></div>

      <div id="schemaEditorWrap" style="display:none">
        <label for="schemaEdit">Schema &mdash; review and edit if needed</label>
        <textarea id="schemaEdit"></textarea>
        <button class="btn btn-success" id="confirmBtn">Confirm Schema &#10003;</button>
      </div>
    </section>

    <!-- ── Step 3: Run Services ── -->
    <section class="card step-card locked" id="step3Card">
      <div class="step-header">
        <div class="step-num" id="num3">3</div>
        <h2>Run Services</h2>
      </div>

      <div class="pipeline-box" id="pipelineBox"></div>

      <button class="btn btn-run" id="runBtn">&#9654; Run Services</button>
      <div class="status" id="runStatus"></div>

      <div class="response-wrap">
        <label>Response</label>
        <div class="response-box" id="runResponse">Results will appear here.</div>
      </div>

      <div id="resultsTableWrap" style="display:none;margin-top:16px">
        <p class="results-section-title">Extracted Results</p>
        <div id="resultsTableContent"></div>
      </div>

      <div id="finalSchemaWrap" style="display:none;margin-top:16px">
        <label style="margin-bottom:6px">Final Schema (instructions used on last attempt)</label>
        <p class="hint">Copy and reuse these refined instructions for future extractions.</p>
        <textarea id="finalSchemaBox" style="width:100%;min-height:120px;font-family:ui-monospace,'Cascadia Code',monospace;font-size:0.8rem;border:1px solid var(--border);border-radius:10px;padding:9px 11px;background:#fff;color:var(--ink);resize:vertical;" readonly></textarea>
        <button class="btn btn-outline" id="copySchemaBtn" style="margin-top:4px">Copy to Clipboard</button>
      </div>
    </section>

  </div>
</div>

<script>
// ─── Modal for document preview ───────────────────────────────────────────────
const modal = document.getElementById('imageModal');
const docPreview = document.getElementById('docPreview');
const modalImage = document.getElementById('modalImage');
const closeModal = document.getElementById('closeModal');

docPreview.addEventListener('click', () => {
  modalImage.src = docPreview.src;
  modal.classList.add('show');
});

closeModal.addEventListener('click', () => {
  modal.classList.remove('show');
});

modal.addEventListener('click', (e) => {
  if (e.target === modal) {
    modal.classList.remove('show');
  }
});

// ─── Data ─────────────────────────────────────────────────────────────────────
const SERVICES = [
  {
    id: 'extraction',
    label: 'Extraction',
    desc: 'Extract fields from document',
    types: ['extraction'],
    pipeline: 'extraction',
    group: 'individual',
  },
  {
    id: 'validation',
    label: 'Validation',
    desc: 'Runs full pipeline: Extract → Validate → Reflect',
    types: ['extraction', 'validation'],
    pipeline: 'extraction_validation_reflect',
    group: 'individual',
  },
  {
    id: 'doc_type_check',
    label: 'Doc Type Check',
    desc: 'Identify document type',
    types: ['doc_type_check'],
    pipeline: 'doc_type_check',
    group: 'individual',
  },
  {
    id: 'doc_type_check_extraction',
    label: 'Doc Check + Extract',
    desc: 'Identify type, then extract fields',
    types: ['doc_type_check', 'extraction'],
    pipeline: 'doc_type_check_extraction',
    group: 'combined',
  },
  {
    id: 'extraction_validation',
    label: 'Extract + Validate',
    desc: 'Extract → Validate → Reflect',
    types: ['extraction', 'validation'],
    pipeline: 'extraction_validation_reflect',
    group: 'combined',
  },
  {
    id: 'all',
    label: 'All Services',
    desc: 'Full pipeline: all steps',
    types: ['doc_type_check', 'extraction', 'validation'],
    pipeline: 'all',
    group: 'combined',
  },
];

const PIPELINE_STEPS = {
  extraction: ['Extraction'],
  doc_type_check: ['Doc Type Check'],
  doc_type_check_extraction: ['Doc Type Check', 'Extraction'],
  extraction_validation_reflect: ['Extraction', 'Validation', 'Reflection'],
  all: ['Doc Type Check', 'Extraction', 'Validation', 'Reflection'],
};

// ─── State ────────────────────────────────────────────────────────────────────
let selected = null;       // current SERVICES entry
let confirmedSchemas = null;

// ─── Helpers ──────────────────────────────────────────────────────────────────
const el = id => document.getElementById(id);
function setStatus(id, msg, type) {
  const s = el(id);
  s.textContent = msg;
  s.className = 'status ' + (type || '');
}

// ─── Build service grids ──────────────────────────────────────────────────────
function buildGrid(containerId, group) {
  const grid = el(containerId);
  SERVICES.filter(s => s.group === group).forEach(svc => {
    const div = document.createElement('div');
    div.className = 'svc-opt';
    div.dataset.id = svc.id;
    div.innerHTML =
      '<div class="svc-name">' + svc.label + '</div>' +
      '<div class="svc-desc">' + svc.desc + '</div>';
    div.addEventListener('click', () => {
      selected = svc;
      document.querySelectorAll('.svc-opt').forEach(d => d.classList.remove('selected'));
      div.classList.add('selected');
      el('step1Btn').disabled = false;
    });
    grid.appendChild(div);
  });
}
buildGrid('indGrid', 'individual');
buildGrid('comGrid', 'combined');

// ─── Step 1: Confirm service selection ───────────────────────────────────────
el('step1Btn').addEventListener('click', () => {
  if (!selected) return;
  el('num1').classList.add('done');
  el('num1').textContent = '✓';
  el('chip1').style.display = '';
  el('step2Card').classList.remove('locked');
  resetStep2();
  el('step2Card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
});

function resetStep2() {
  setStatus('schemaStatus', '', '');
  el('schemaEditorWrap').style.display = 'none';
  el('schemaEdit').value = '';
  el('nlInput').value = '';
  el('manualInput').value = '';
  el('chip2').style.display = 'none';
  el('num2').classList.remove('done');
  el('num2').textContent = '2';
}

// ─── Schema source tabs ────────────────────────────────────────────────────────
function setActiveTab(activeId) {
  ['tabPre', 'tabNL', 'tabManual'].forEach(id => el(id).classList.remove('active'));
  ['preSection', 'nlSection', 'manualSection'].forEach(id => el(id).style.display = 'none');
  el(activeId).classList.add('active');
  el({ tabPre: 'preSection', tabNL: 'nlSection', tabManual: 'manualSection' }[activeId]).style.display = '';
  el('schemaEditorWrap').style.display = 'none';
  setStatus('schemaStatus', '', '');
}

el('tabPre').addEventListener('click', () => setActiveTab('tabPre'));
el('tabNL').addEventListener('click', () => setActiveTab('tabNL'));
el('tabManual').addEventListener('click', () => setActiveTab('tabManual'));

// ─── Load predefined schema ────────────────────────────────────────────────────
el('loadPreBtn').addEventListener('click', async () => {
  setStatus('schemaStatus', 'Loading…', 'info');
  try {
    const res = await fetch('/predefined-schema', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ service_types: selected.types }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Load failed');
    showSchemaEditor(data.schemas);
    setStatus('schemaStatus', 'Predefined schema loaded. Review then confirm.', 'ok');
  } catch (err) {
    setStatus('schemaStatus', 'Error: ' + err.message, 'err');
  }
});

// ─── Parse natural language ────────────────────────────────────────────────────
el('parseBtn').addEventListener('click', async () => {
  const nl = el('nlInput').value.trim();
  if (!nl) { setStatus('schemaStatus', 'Please enter a description first.', 'err'); return; }
  setStatus('schemaStatus', 'Parsing with AI…', 'info');
  el('schemaEditorWrap').style.display = 'none';
  try {
    const res = await fetch('/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ natural_language: nl, service_types: selected.types }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Parse failed');
    showSchemaEditor(data.schemas);
    setStatus('schemaStatus', 'Schema generated. Review then confirm.', 'ok');
  } catch (err) {
    setStatus('schemaStatus', 'Error: ' + err.message, 'err');
  }
});

function showSchemaEditor(schemas) {
  el('schemaEdit').value = JSON.stringify(schemas, null, 2);
  el('schemaEditorWrap').style.display = '';
}

// ─── Load manual schema ────────────────────────────────────────────────────────
el('loadManualBtn').addEventListener('click', () => {
  const raw = el('manualInput').value.trim();
  if (!raw) { setStatus('schemaStatus', 'Paste a schema first.', 'err'); return; }
  try {
    const parsed = JSON.parse(raw);
    showSchemaEditor(parsed);
    setStatus('schemaStatus', 'Schema loaded. Review then confirm.', 'ok');
  } catch {
    setStatus('schemaStatus', 'Invalid JSON — check your input.', 'err');
  }
});

// ─── Confirm schema ────────────────────────────────────────────────────────────
el('confirmBtn').addEventListener('click', () => {
  let parsed;
  try {
    parsed = JSON.parse(el('schemaEdit').value.trim());
  } catch {
    setStatus('schemaStatus', 'Invalid JSON — fix before confirming.', 'err');
    return;
  }
  confirmedSchemas = parsed;
  el('num2').classList.add('done');
  el('num2').textContent = '✓';
  el('chip2').style.display = '';
  setStatus('schemaStatus', 'Schema confirmed ✓', 'ok');
  el('step3Card').classList.remove('locked');
  buildPipelineBox();
  el('step3Card').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  setStatus('runStatus', '', '');
  el('runResponse').textContent = 'Results will appear here.';
});

// ─── Step 3: pipeline info ─────────────────────────────────────────────────────
function buildPipelineBox() {
  const steps = PIPELINE_STEPS[selected.pipeline] || [selected.label];
  let html = '<div class="pl-label">Pipeline: ' + selected.label + '</div><div class="pl-steps">';
  steps.forEach((s, i) => {
    if (i > 0) html += '<span class="pl-arrow">→</span>';
    html += '<span class="pl-step">' + s + '</span>';
  });
  html += '</div>';
  el('pipelineBox').innerHTML = html;
}

// ─── Results table ────────────────────────────────────────────────────────────
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatFieldName(key) {
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function renderResultsTable(data) {
  const wrap = el('resultsTableWrap');
  const container = el('resultsTableContent');
  container.innerHTML = '';

  const extractedData =
    data?.reflection?.extracted_data ||
    data?.extraction?.extracted_data ||
    {};

  const docType =
    data?.doc_type_check?.extracted_data?.document_type ||
    data?.doc_type_check?.document_type ||
    null;

  const validationStatus =
    data?.reflection?.status ||
    data?.validation?.status ||
    null;

  const validationFeedback =
    data?.reflection?.validation?.feedback ||
    data?.validation?.feedback ||
    null;

  const attempt = data?.reflection?.attempt || null;

  const hasExtracted = Object.keys(extractedData).length > 0;
  if (!hasExtracted && !docType && !validationStatus) {
    wrap.style.display = 'none';
    return;
  }

  let html = '<div class="results-summary">';
  if (docType) {
    html +=
      '<div class="summary-chip">' +
      '<div class="summary-chip-label">Document Type</div>' +
      '<div class="summary-chip-value">' + escapeHtml(docType) + '</div>' +
      '</div>';
  }
  if (validationStatus) {
    const isValid = validationStatus.toLowerCase() === 'valid';
    html +=
      '<div class="summary-chip">' +
      '<div class="summary-chip-label">Validation</div>' +
      '<span class="status-badge ' + (isValid ? 'valid' : 'invalid') + '">' +
      (isValid ? '&#10003; Valid' : '&#10007; Invalid') +
      '</span></div>';
  }
  if (attempt) {
    html +=
      '<div class="summary-chip">' +
      '<div class="summary-chip-label">Completed In</div>' +
      '<div class="summary-chip-value">' + attempt + ' attempt' + (attempt > 1 ? 's' : '') + '</div>' +
      '</div>';
  }
  html += '</div>';

  if (validationFeedback && validationStatus && validationStatus.toLowerCase() !== 'valid') {
    html +=
      '<div class="validation-feedback"><strong>Validation Feedback:</strong> ' +
      escapeHtml(validationFeedback) +
      '</div>';
  }

  if (hasExtracted) {
    html += '<table class="results-table"><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>';
    for (const [key, value] of Object.entries(extractedData)) {
      const displayValue =
        value === null || value === undefined
          ? '<em style="color:var(--muted)">—</em>'
          : typeof value === 'object'
            ? '<code style="font-size:0.78rem">' + escapeHtml(JSON.stringify(value)) + '</code>'
            : escapeHtml(String(value));
      html +=
        '<tr><td class="field-name">' + escapeHtml(formatFieldName(key)) + '</td>' +
        '<td>' + displayValue + '</td></tr>';
    }
    html += '</tbody></table>';
  }

  container.innerHTML = html;
  wrap.style.display = '';
}

// ─── Run services ──────────────────────────────────────────────────────────────
function withFilename(schemas) {
  const s = JSON.parse(JSON.stringify(schemas));
  if (s.extraction) s.extraction.image_filename = currentFilename;
  if (s.doc_type_check) s.doc_type_check.image_filename = currentFilename;
  return s;
}

el('runBtn').addEventListener('click', async () => {
  setStatus('runStatus', 'Running services…', 'info');

  const progressMessages = [
    'Starting API call...',
    'Attempt 1: sending extraction request...',
    'Attempt 1: waiting for extraction response...',
    'Attempt 1: validating extracted data...',
    'Attempt 1: running reflection agent...',
    'Attempt 2: sending extraction request...',
    'Attempt 2: waiting for extraction response...',
    'Attempt 2: validating extracted data...',
    'Attempt 2: running reflection agent...',
    'Finalising results...',
  ];
  let msgIdx = 0;
  el('runResponse').textContent = progressMessages[0];
  const ticker = setInterval(() => {
    msgIdx = Math.min(msgIdx + 1, progressMessages.length - 1);
    el('runResponse').textContent = progressMessages[msgIdx];
  }, 2500);

  try {
    const res = await fetch('/call-api', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pipeline: selected.pipeline, schemas: withFilename(confirmedSchemas) }),
    });
    clearInterval(ticker);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'API call failed');
    el('runResponse').textContent = JSON.stringify(data, null, 2);
    setStatus('runStatus', 'Done ✓', 'ok');
    renderResultsTable(data);
    const finalSchema = data?.reflection?.final_schema || data?.final_schema;
    if (finalSchema) {
      el('finalSchemaBox').value = finalSchema;
      el('finalSchemaWrap').style.display = '';
    } else {
      el('finalSchemaWrap').style.display = 'none';
    }
  } catch (err) {
    clearInterval(ticker);
    setStatus('runStatus', 'Error: ' + err.message, 'err');
    el('runResponse').textContent = err.message;
    el('resultsTableWrap').style.display = 'none';
  }
});

// ─── Document loading ─────────────────────────────────────────────────────────
let currentFilename = 'dummy_invoice.png';
const IMAGE_EXTS = ['png', 'jpg', 'jpeg'];

function applyDocResult(data) {
  currentFilename = data.filename;
  const ext = data.filename.split('.').pop().toLowerCase();
  if (IMAGE_EXTS.includes(ext)) {
    el('docPreview').src = data.url + '?t=' + Date.now();
    el('docPreview').style.display = '';
    el('pdfNote').style.display = 'none';
  } else {
    el('docPreview').style.display = 'none';
    el('pdfNote').textContent = data.filename + ' loaded (PDF — no image preview)';
    el('pdfNote').style.display = '';
  }
  setStatus('docStatus', data.filename + ' ✓', 'ok');
}

// Tab switching
el('tabUpload').addEventListener('click', () => {
  el('tabUpload').classList.add('active'); el('tabPath').classList.remove('active');
  el('uploadSection').style.display = ''; el('pathSection').style.display = 'none';
  setStatus('docStatus', '', '');
});
el('tabPath').addEventListener('click', () => {
  el('tabPath').classList.add('active'); el('tabUpload').classList.remove('active');
  el('pathSection').style.display = ''; el('uploadSection').style.display = 'none';
  setStatus('docStatus', '', '');
});

// Browse / drag-drop upload
const uploadArea = el('uploadArea');
el('browseBtn').addEventListener('click', () => el('fileInput').click());
uploadArea.addEventListener('click', e => { if (e.target.id !== 'browseBtn') el('fileInput').click(); });
uploadArea.addEventListener('dragover', e => { e.preventDefault(); uploadArea.classList.add('drag-over'); });
uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('drag-over'));
uploadArea.addEventListener('drop', e => {
  e.preventDefault(); uploadArea.classList.remove('drag-over');
  const f = e.dataTransfer.files[0]; if (f) sendFile(f);
});
el('fileInput').addEventListener('change', () => { if (el('fileInput').files[0]) sendFile(el('fileInput').files[0]); });

async function sendFile(file) {
  setStatus('docStatus', 'Uploading…', 'info');
  try {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/upload-file', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Upload failed');
    applyDocResult(data);
  } catch (err) {
    setStatus('docStatus', 'Error: ' + err.message, 'err');
  }
}

// Copy final schema
el('copySchemaBtn').addEventListener('click', () => {
  navigator.clipboard.writeText(el('finalSchemaBox').value).then(() => {
    el('copySchemaBtn').textContent = 'Copied ✓';
    setTimeout(() => { el('copySchemaBtn').textContent = 'Copy to Clipboard'; }, 2000);
  });
});

// File path method
el('loadDocBtn').addEventListener('click', async () => {
  const filepath = el('docPath').value.trim();
  if (!filepath) { setStatus('docStatus', 'Enter a file path first.', 'err'); return; }
  setStatus('docStatus', 'Loading…', 'info');
  try {
    const res = await fetch('/upload-document', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filepath }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Load failed');
    applyDocResult(data);
  } catch (err) {
    setStatus('docStatus', 'Error: ' + err.message, 'err');
  }
});
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("UI:app", host="0.0.0.0", port=8001, reload=True)
