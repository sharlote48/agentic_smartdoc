import json
import os
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI


def _create_llm() -> ChatGoogleGenerativeAI:
	"""Create a ChatGoogleGenerativeAI instance with gemini-2.5-flash-lite."""
	load_dotenv()
	api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GENAI_API_KEY")
	if not api_key:
		raise ValueError("Set GOOGLE_API_KEY or GENAI_API_KEY in environment/.env")

	return ChatGoogleGenerativeAI(
		model="gemini-2.5-flash-lite",
		temperature=0,
		max_retries=3,
	)


def parse_natural_language_to_payload(natural_language_prompt: str) -> Dict[str, Any]:
	"""
	Convert natural language into a payload.json-compatible structure.

	Args:
		natural_language_prompt: A natural language description of what fields to extract

	Returns:
		A dictionary with structure matching payload.json:
		{
			"image_filename": "dummy_invoice.png",
			"instructions": "...",
			"fields": [...]
		}
	"""
	llm = _create_llm()

	system_prompt = """You are an expert at converting natural language descriptions into structured extraction configs.
Given a natural language prompt describing what fields to extract from an image, output a valid JSON object with this exact structure:

{
  "image_filename": "dummy_invoice.png",
  "instructions": "A clear instruction for extracting the described fields",
  "fields": [
    {
      "name": "field_name_in_snake_case",
      "type": "string|integer|float|boolean|list[string]|list[integer]|list[float]|list[boolean]",
      "required": true/false,
      "description": "Clear description of what this field contains"
    }
  ]
}

Supported field types:
- string
- integer
- float
- boolean
- list[string]
- list[integer]
- list[float]
- list[boolean]

Rules:
1. Use "string" as the default type unless the field clearly expects numbers or lists
2. Mark fields as required=true unless they are optional
3. Make descriptions clear and actionable
4. Always use "dummy_invoice.png" as the image_filename
5. Generate meaningful extraction instructions based on the prompt
6. Return ONLY valid JSON, no markdown, no explanations"""

	user_message = f"""Convert this natural language prompt into a structured extraction config:

{natural_language_prompt}

Output only the JSON object, nothing else."""

	messages = [
		SystemMessage(content=system_prompt),
		HumanMessage(content=user_message),
	]

	response = llm.invoke(messages)
	result_text = str(response.content).strip()

	# Clean markdown code blocks if present
	if result_text.startswith("```json"):
		result_text = result_text[7:]
	if result_text.startswith("```"):
		result_text = result_text[3:]
	if result_text.endswith("```"):
		result_text = result_text[:-3]

	result_text = result_text.strip()

	# Parse and validate JSON
	payload = json.loads(result_text)

	# Ensure all required keys are present
	if "image_filename" not in payload:
		payload["image_filename"] = "dummy_invoice.png"
	if "instructions" not in payload:
		payload["instructions"] = "Extract the requested fields accurately."
	if "fields" not in payload or not isinstance(payload["fields"], list):
		raise ValueError("Response must contain a 'fields' array")

	return payload


def main():
	"""Interactive CLI for parsing natural language into payload."""
	print("=" * 70)
	print("Natural Language to Payload Parser")
	print("Powered by Gemini 2.5 Flash Lite")
	print("=" * 70)
	print()

	# Example usage
	sample_prompt = """Extract invoice data: invoice number, vendor/company name, 
	date the invoice was issued, total amount due, currency symbol, and 
	a list of all line items (products/services listed)."""

	print("Example natural language prompt:")
	print(f"  {sample_prompt}")
	print()

	# Get user input
	user_input = input("Enter your natural language extraction request (or press Enter for example): ").strip()
	if not user_input:
		user_input = sample_prompt

	print("\nProcessing with Gemini 2.5 Flash Lite...")
	print()

	try:
		payload = parse_natural_language_to_payload(user_input)

		print("Generated Payload:")
		print("-" * 70)
		print(json.dumps(payload, indent=2))
		print("-" * 70)
		print()

		# Ask if user wants to save
		save = input("Save to file? (y/n): ").strip().lower()
		if save == "y":
			filename = input("Enter filename (default: payload_generated.json): ").strip()
			if not filename:
				filename = "payload_generated.json"

			with open(filename, "w") as f:
				json.dump(payload, f, indent=2)

			print(f"✓ Saved to {filename}")

	except json.JSONDecodeError as e:
		print(f"❌ Error parsing JSON response: {e}")
		print("Response was not valid JSON")
	except Exception as e:
		print(f"❌ Error: {e}")


if __name__ == "__main__":
	main()
