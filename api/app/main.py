from fastapi import FastAPI

app = FastAPI(title="Fraud Detection API")


@app.get("/health")
def health() -> dict[str, str]:
    """Health check used by the ALB."""
    return {"status": "ok"}
