import asyncio
import js
from pyscript import document
from pyodide.ffi import create_proxy

# Helper to log messages to the UI console
def log_to_ui(message):
    print(message)
    log_container = document.getElementById("log-container")
    if log_container:
        entry = document.createElement("div")
        entry.innerText = f">> {message}"
        log_container.appendChild(entry)
        log_container.scrollTop = log_container.scrollHeight

async def process_images(event):
    log_to_ui("Starting processing...")
    files = js.window.selected_files
    
    if not files or files.length == 0:
        log_to_ui("No files selected!")
        return

    log_to_ui(f"Found {files.length} files.")
    
    # TODO: Implement OpenCV logic here
    log_to_ui("Processing logic not yet implemented.")

def setup():
    start_btn = document.getElementById("start-btn")
    if start_btn:
        on_click_proxy = create_proxy(process_images)
        start_btn.addEventListener("click", on_click_proxy)
        js.console.log("Event listener attached to start-btn")
    
    # Signal that Python is ready
    loader = document.getElementById("env-loader")
    if loader:
        loader.style.display = "none" # Force hide for now to show UI
    
    log_to_ui("System Ready (Python initialized)")

if __name__ == "__main__":
    setup()