from fastapi import FastAPI

from extraction_service import router as extraction_router
from reflection import router as reflection_router
from validation_service import router as validation_router


app = FastAPI(
	title="Document Processing API",
	description="Extraction and validation services for agentic workflows",
	version="1.0.0",
)

app.include_router(extraction_router)
app.include_router(reflection_router)
app.include_router(validation_router)


@app.get("/")
def health() -> dict[str, str]:
	return {"status": "ok", "service": "document-processing"}


if __name__ == "__main__":
	import uvicorn

	uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
