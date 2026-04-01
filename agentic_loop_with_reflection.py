import asyncio
import json
from pathlib import Path
from typing import List, Dict, Any

import httpx


async def universal_agent_loop(
    extraction_fields: List[Dict[str, Any]],
    validation_rules: List[Dict[str, Any]],
    *,
    image_filename: str = "dummy_invoice.png",
    base_url: str = "http://127.0.0.1:8000",
    max_attempts: int = 5,
) -> Dict[str, Any]:
    """Run extraction -> validation -> reflection loop."""

    base_instructions = "Extract the requested data accurately from the document."
    current_instructions = base_instructions
    last_feedback = "Validation did not pass."

    extract_url = f"{base_url.rstrip('/')}/extract-image"
    validate_url = f"{base_url.rstrip('/')}/validate"
    reflect_url = f"{base_url.rstrip('/')}/reflect"  # NEW

    attempt_history = []  # NEW (optional but recommended)

    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(1, max_attempts + 1):

            extraction_payload = {
                "image_filename": image_filename,
                "fields": extraction_fields,
                "instructions": current_instructions,
            }

            print(f"Attempt {attempt}: Sending extraction request")
            print(f"Instructions:\n{current_instructions}\n")

            extract_res = await client.post(extract_url, json=extraction_payload)
            extract_res.raise_for_status()

            extract_out = extract_res.json()
            extracted_data = extract_out.get("extracted_data", {})

            print(f"Extracted data: {json.dumps(extracted_data, indent=2)}")

            # Validation
            validation_payload = {
                "data": extracted_data,
                "rules": validation_rules,
            }

            validate_res = await client.post(validate_url, json=validation_payload)
            validate_res.raise_for_status()

            validation_out = validate_res.json()
            status = str(validation_out.get("status", "")).lower()
            feedback = validation_out.get("feedback", "No validation feedback provided.")

            # Success
            if status == "valid":
                return {
                    "status": "valid",
                    "attempt": attempt,
                    "mode": "image",
                    "extracted_data": extracted_data,
                    "validation": validation_out,
                }

            # Failure
            last_feedback = str(feedback)

            print(f"Attempt {attempt} failed validation:")
            print(last_feedback)

            # Save history (NEW)
            attempt_history.append({
                "attempt": attempt,
                "extracted_data": extracted_data,
                "feedback": last_feedback,
            })

            # ---------------------------
            # Reflection Step (NEW)
            # ---------------------------

            reflection_payload = {
                "fields": extraction_fields,
                "previous_extraction": extracted_data,
                "validation_feedback": last_feedback,
                "attempt_history": attempt_history,
                "current_instructions": current_instructions,
            }

            print("Calling reflection agent...\n")

            reflect_res = await client.post(reflect_url, json=reflection_payload)
            reflect_res.raise_for_status()

            reflect_out = reflect_res.json()
            updated = reflect_out.get("updated_instructions")
            if isinstance(updated, str) and updated.strip():
                current_instructions = updated

            print("Updated Instructions:")
            print(current_instructions)
            print("\n" + "-" * 60 + "\n")

    return {
        "status": "invalid",
        "attempt": max_attempts,
        "mode": "image",
        "feedback": last_feedback,
        "extracted_data": {},
    }


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


async def _run_demo() -> None:
    base_dir = Path(__file__).parent
    extraction_config = _load_json(base_dir / "payload.json")
    validation_config = _load_json(base_dir / "validation_payload.json")

    extraction_fields = extraction_config.get("fields", [])
    validation_rules = validation_config.get("rules", [])

    if not extraction_fields:
        raise ValueError("payload.json is missing non-empty 'fields'.")
    if not validation_rules:
        raise ValueError("validation_payload.json is missing non-empty 'rules'.")

    image_filename = extraction_config.get("image_filename", "dummy_invoice.png")
    print(f"Running image mode with: {image_filename}")

    result = await universal_agent_loop(
        extraction_fields=extraction_fields,
        validation_rules=validation_rules,
        image_filename=image_filename,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(_run_demo())