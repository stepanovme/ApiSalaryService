import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "app.api:app",
        host="0.0.0.0",
        port=8392,
        reload=True,
        log_level="info",
    )