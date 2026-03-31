from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse


app = FastAPI(
	title="Invoice Extraction UI",
	description="UI client for the document extraction API",
	version="1.0.0",
)


@app.get("/")
def health() -> dict[str, str]:
	return {"status": "ok", "service": "extraction-ui"}


@app.get("/assets/dummy_invoice.png")
def get_dummy_invoice() -> FileResponse:
	image_path = Path(__file__).parent / "dummy_invoice.png"
	if not image_path.exists():
		raise HTTPException(status_code=404, detail="dummy_invoice.png not found")
	return FileResponse(image_path)


@app.get("/ui", response_class=HTMLResponse)
def extraction_ui() -> HTMLResponse:
	html = """
<!doctype html>
<html lang="en">
<head>
	<meta charset="UTF-8" />
	<meta name="viewport" content="width=device-width, initial-scale=1.0" />
	<title>Invoice Extraction UI</title>
	<style>
		:root {
			--bg: #f3efe8;
			--panel: #fffaf2;
			--ink: #1d2b36;
			--muted: #6b7680;
			--accent: #005f73;
			--accent-2: #ee9b00;
			--border: #d8cec0;
		}
		* { box-sizing: border-box; }
		body {
			margin: 0;
			font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
			color: var(--ink);
			background:
				radial-gradient(circle at 10% 20%, #fff6df, transparent 28%),
				radial-gradient(circle at 85% 80%, #d4ecef, transparent 28%),
				var(--bg);
			min-height: 100vh;
			padding: 24px;
		}
		.wrap {
			max-width: 1100px;
			margin: 0 auto;
			display: grid;
			grid-template-columns: 1.1fr 1fr;
			gap: 20px;
		}
		.card {
			background: var(--panel);
			border: 1px solid var(--border);
			border-radius: 14px;
			padding: 18px;
			box-shadow: 0 10px 24px rgba(0, 0, 0, 0.05);
		}
		h1 {
			margin: 0 0 8px;
			font-size: 1.5rem;
			letter-spacing: 0.01em;
		}
		p { margin: 0 0 12px; color: var(--muted); }
		img {
			width: 100%;
			border: 1px solid var(--border);
			border-radius: 10px;
			background: white;
			object-fit: contain;
		}
		label {
			display: block;
			font-weight: 600;
			margin-bottom: 6px;
		}
		textarea, input {
			width: 100%;
			border: 1px solid var(--border);
			border-radius: 10px;
			padding: 10px;
			background: #fff;
			color: var(--ink);
			font-size: 0.95rem;
			margin-bottom: 12px;
		}
		textarea { min-height: 170px; resize: vertical; }
		button {
			border: none;
			border-radius: 10px;
			background: linear-gradient(90deg, var(--accent), #0a9396);
			color: #fff;
			font-weight: 700;
			padding: 11px 14px;
			cursor: pointer;
			width: 100%;
		}
		button:hover { filter: brightness(1.05); }
		.tip {
			font-size: 0.85rem;
			color: var(--muted);
			margin-top: -4px;
			margin-bottom: 12px;
		}
		pre {
			white-space: pre-wrap;
			word-break: break-word;
			background: #102331;
			color: #d7ebf4;
			border-radius: 10px;
			padding: 12px;
			min-height: 140px;
			overflow: auto;
		}
		.status {
			margin: 10px 0;
			font-weight: 600;
			color: var(--accent-2);
			min-height: 24px;
		}
		@media (max-width: 900px) {
			.wrap { grid-template-columns: 1fr; }
		}
	</style>
</head>
<body>
	<div class="wrap">
		<section class="card">
			<h1>Invoice Extraction Playground</h1>
			<p>Image input is fixed to dummy_invoice.png. Enter fields to extract and run.</p>
			<img src="/assets/dummy_invoice.png" alt="Dummy invoice" />
		</section>

		<section class="card">
			<label for="apiBase">API Base URL</label>
			<input id="apiBase" value="http://127.0.0.1:8000" />

			<label for="instructions">Instructions</label>
			<input id="instructions" value="Extract invoice details accurately from this image." />

			<label for="fields">Fields to extract</label>
			<p class="tip">Formats: name OR name:type OR name|type|required|description</p>
			<textarea id="fields">invoice_number|string|true|Invoice id or number
invoice_date|string|false|Date the invoice was issued
vendor_name|string|true|Vendor or seller name
total_amount|float|true|Total amount due
currency|string|false|Currency code or symbol
line_items|list[string]|false|Product or service line items</textarea>

			<button id="runBtn">Run Extraction</button>
			<div class="status" id="status"></div>

			<label>Generated API payload</label>
			<pre id="payload"></pre>
			<label>API response</label>
			<pre id="output"></pre>
		</section>
	</div>

	<script>
		const runBtn = document.getElementById('runBtn');
		const apiBaseEl = document.getElementById('apiBase');
		const fieldsEl = document.getElementById('fields');
		const instructionsEl = document.getElementById('instructions');
		const payloadEl = document.getElementById('payload');
		const outputEl = document.getElementById('output');
		const statusEl = document.getElementById('status');
		const allowedTypes = new Set([
			'string', 'integer', 'float', 'boolean',
			'list[string]', 'list[integer]', 'list[float]', 'list[boolean]'
		]);

		function parseFieldLines(text) {
			const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
			return lines.map((line, idx) => {
				let name = '';
				let type = 'string';
				let required = true;
				let description = '';

				if (line.includes('|')) {
					const parts = line.split('|');
					name = (parts[0] || '').trim();
					type = ((parts[1] || 'string').trim() || 'string').toLowerCase();
					if (parts[2]) {
						required = parts[2].trim().toLowerCase() === 'true';
					}
					description = parts.slice(3).join('|').trim();
				} else if (line.includes(':')) {
					const [rawName, rawType] = line.split(':', 2);
					name = (rawName || '').trim();
					type = ((rawType || 'string').trim() || 'string').toLowerCase();
				} else {
					name = line.trim();
				}

				if (!name) {
					throw new Error(`Line ${idx + 1} has an empty field name.`);
				}
				if (!allowedTypes.has(type)) {
					throw new Error(
						`Line ${idx + 1} has unsupported type "${type}". Use one of: ${Array.from(allowedTypes).join(', ')}`
					);
				}

				return { name, type, required, description };
			});
		}

		async function runExtraction() {
			try {
				statusEl.textContent = 'Preparing payload...';
				outputEl.textContent = '';

				const fields = parseFieldLines(fieldsEl.value);
				const payload = {
					image_filename: 'dummy_invoice.png',
					instructions: instructionsEl.value,
					fields,
				};

				payloadEl.textContent = JSON.stringify(payload, null, 2);
				statusEl.textContent = 'Calling extraction API...';

				const endpoint = `${apiBaseEl.value.replace(/\/$/, '')}/extract-image`;
				const res = await fetch(endpoint, {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify(payload),
				});

				const data = await res.json();
				if (!res.ok) {
					throw new Error(data.detail || 'Extraction failed');
				}

				outputEl.textContent = JSON.stringify(data, null, 2);
				statusEl.textContent = 'Done.';
			} catch (err) {
				statusEl.textContent = 'Error.';
				payloadEl.textContent = payloadEl.textContent || 'Payload generation failed before request.';
				outputEl.textContent = err.message || String(err);
			}
		}

		runBtn.addEventListener('click', runExtraction);
		payloadEl.textContent = 'Payload will appear here after you click Run Extraction.';
		outputEl.textContent = 'Response will appear here.';
	</script>
</body>
</html>
"""
	return HTMLResponse(content=html)


if __name__ == "__main__":
	import uvicorn

	uvicorn.run("UI:app", host="0.0.0.0", port=8001, reload=True)
