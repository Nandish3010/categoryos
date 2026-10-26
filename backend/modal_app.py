import modal

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi",
        "uvicorn[standard]",
        "pydantic>=2",
        "pydantic-settings",
        "httpx",
        "openai",
        "python-dotenv",
        "python-multipart",
    )
    .add_local_python_source("app")
)

app = modal.App("categoryos-backend", image=image)


@app.function()
@modal.asgi_app()
def fastapi_app():
    from app.main import app as web_app

    return web_app
