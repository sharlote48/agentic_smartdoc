import json
from pathlib import Path
from typing import Any, Dict

import requests

from natural_language_parser import parse_natural_language_to_payload

BASE_URL = "http://127.0.0.1:8000"
EXTRACTION_PAYLOAD_PATH = Path(__file__).with_name("payload.json")
VALIDATION_PAYLOAD_PATH = Path(__file__).with_name("validation_payload.json")
REFLECTION_PAYLOAD_PATH = Path(__file__).with_name("reflection_payload.json")


def _select_mode() -> str:
	print("Choose which service to run:")
	print("1) extraction")
	print("2) validation")
	print("3) both")
	print("4) reflect")
	print("5) all (extraction -> validation -> reflect)")
	choice = input("Enter 1, 2, 3, 4, or 5: ").strip().lower()

	mapping = {
		"1": "extraction",
		"2": "validation",
		"3": "both",
		"4": "reflect",
		"5": "all",
		"extraction": "extraction",
		"validation": "validation",
		"both": "both",
		"reflect": "reflect",
		"all": "all",
	}

	if choice not in mapping:
		raise ValueError("Invalid choice. Use 1/2/3/4/5 or extraction/validation/both/reflect/all.")

	return mapping[choice]


def _load_reflection_payload() -> Dict[str, Any]:
	if not REFLECTION_PAYLOAD_PATH.exists():
		raise FileNotFoundError(f"Missing payload file: {REFLECTION_PAYLOAD_PATH}")
	with REFLECTION_PAYLOAD_PATH.open("r", encoding="utf-8") as reflection_payload_file:
		return json.load(reflection_payload_file)


def _prompt_validation_data() -> Dict[str, Any]:
	print("Validation-only mode requires data to validate.")
	print("Paste extracted_data JSON (example: {\"currency\":\"USD\",\"total_amount\":120.5})")
	raw = input("extracted_data JSON: ").strip()
	if not raw:
		raise ValueError("No validation data provided.")
	parsed = json.loads(raw)
	if not isinstance(parsed, dict):
		raise ValueError("Validation data must be a JSON object.")
	return parsed


def _select_extraction_input_source() -> str:
	print("Choose extraction payload source:")
	print("1) Use the existing payload.json file")
	print("2) Enter a natural language extraction request")
	choice = input("Enter 1 or 2: ").strip().lower()
	if choice in ("1", "file"):
		return "file"
	if choice in ("2", "nl", "natural", "natural language"):
		return "natural_language"
	raise ValueError("Invalid choice. Use 1 or 2.")


def _prompt_natural_language_payload() -> Dict[str, Any]:
	print("Enter a natural language description of the fields to extract.")
	print("For example: Extract invoice number, vendor name, invoice date, total amount, currency, and line items.")
	nl_prompt = input("Natural language request: ").strip()
	if not nl_prompt:
		raise ValueError("Natural language request cannot be empty.")
	print("Parsing request into extraction payload...")
	payload = parse_natural_language_to_payload(nl_prompt)
	if not isinstance(payload, dict):
		raise ValueError("Parsed payload must be a JSON object.")
	return payload


def main() -> None:
	mode = _select_mode()

	extraction_payload = None
	validation_payload = None

	if mode in ("extraction", "both", "all"):
		input_source = _select_extraction_input_source()
		if input_source == "file":
			if not EXTRACTION_PAYLOAD_PATH.exists():
				raise FileNotFoundError(f"Missing payload file: {EXTRACTION_PAYLOAD_PATH}")
			with EXTRACTION_PAYLOAD_PATH.open("r", encoding="utf-8") as extraction_payload_file:
				extraction_payload = json.load(extraction_payload_file)
		else:
			extraction_payload = _prompt_natural_language_payload()

	if mode in ("validation", "both", "all"):
		if not VALIDATION_PAYLOAD_PATH.exists():
			raise FileNotFoundError(f"Missing payload file: {VALIDATION_PAYLOAD_PATH}")
		with VALIDATION_PAYLOAD_PATH.open("r", encoding="utf-8") as validation_payload_file:
			validation_payload = json.load(validation_payload_file)
		if "rules" not in validation_payload:
			raise ValueError("validation_payload.json must include a 'rules' key.")

	reflection_payload: Dict[str, Any] = {}
	if mode in ("reflect",):
		reflection_payload = _load_reflection_payload()

	health_response = requests.get(f"{BASE_URL}/", timeout=10)
	health_response.raise_for_status()
	print("Health:", health_response.json())

	extracted_data: Dict[str, Any] = {}

	if mode in ("extraction", "both", "all"):
		if extraction_payload is None:
			raise ValueError("Extraction payload is required for extraction mode.")
		extract_response = requests.post(
			f"{BASE_URL}/extract-image",
			json=extraction_payload,
			timeout=120,
		)
		print("Extraction Status:", extract_response.status_code)
		print(extract_response.text)
		if not extract_response.ok:
			extract_response.raise_for_status()
		extract_output = extract_response.json()
		extracted_data = extract_output.get("extracted_data", {})

	validation_output: Dict[str, Any] = {}
	if mode in ("validation", "both", "all"):
		if mode == "validation":
			if "data" in validation_payload and isinstance(validation_payload["data"], dict):
				extracted_data = validation_payload["data"]
			else:
				extracted_data = _prompt_validation_data()
		validation_request = {
			"data": extracted_data,
			"rules": validation_payload["rules"],
		}
		validation_response = requests.post(
			f"{BASE_URL}/validate",
			json=validation_request,
			timeout=120,
		)
		print("Validation Status:", validation_response.status_code)
		print(validation_response.text)
		if not validation_response.ok:
			validation_response.raise_for_status()
		validation_output = validation_response.json()

	if mode in ("reflect", "all"):
		if mode == "all":
			reflection_payload = {
				"fields": extraction_payload.get("fields", []),
				"previous_extraction": extracted_data,
				"validation_feedback": validation_output.get("feedback", "No validation feedback provided."),
				"attempt_history": [
					{
						"attempt": 1,
						"extracted_data": extracted_data,
						"feedback": validation_output.get("feedback", "No validation feedback provided."),
					}
				],
				"current_instructions": extraction_payload.get(
					"instructions", "Extract the requested data accurately from the document."
				),
			}

		reflect_response = requests.post(
			f"{BASE_URL}/reflect",
			json=reflection_payload,
			timeout=120,
		)
		print("Reflection Status:", reflect_response.status_code)
		print(reflect_response.text)
		if not reflect_response.ok:
			reflect_response.raise_for_status()


if __name__ == "__main__":
	main()