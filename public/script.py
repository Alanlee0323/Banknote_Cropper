import asyncio
import js
from pyscript import document
from pyodide.ffi import create_proxy
import io
import zipfile
import sys

# Setup JS console logger
def log(msg):
    js.console.log(f"[Python] {msg}")
    print(f"[Python] {msg}")
    # Also try to update UI directly if possible
    status = document.getElementById("status-text")
    if status:
        status.innerText = msg

log("Script loading started...")

cv2 = None
np = None

async def install_opencv():
    log("Importing micropip...")
    try:
        import micropip
        log("micropip imported.")
    except ImportError as e:
        log(f"Failed to import micropip: {e}")
        return False

    log("Installing opencv-python via micropip...")
    try:
        loader_status = document.getElementById("loader-status")
        if loader_status:
            loader_status.innerText = "Downloading OpenCV (this may take a moment)..."
        
        await micropip.install("opencv-python")
        log("micropip install completed.")
        return True
    except Exception as e:
        log(f"Failed to install opencv-python: {e}")
        if loader_status:
            loader_status.innerText = f"Install Failed: {e}"
        return False

async def ensure_dependencies():
    global cv2, np
    log("Checking dependencies...")
    
    try:
        import cv2 as _cv2
        import numpy as _np
        cv2 = _cv2
        np = _np
        log("OpenCV already available.")
    except ImportError:
        log("OpenCV not found. Attempting installation...")
        success = await install_opencv()
        if not success:
            log("Critical: OpenCV installation failed.")
            return

        try:
            import cv2 as _cv2
            import numpy as _np
            cv2 = _cv2
            np = _np
            log("OpenCV imported successfully after install.")
        except ImportError as e:
            log(f"Import failed even after install: {e}")

# --- Core Logic ---

def crop_banknote(image_bytes):
    if cv2 is None:
        log("Error: cv2 is None during crop attempt")
        return None
        
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None: return None

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 30, 150)
        contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours: return None

        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        x, y, w, h = cv2.boundingRect(contours[0])
        
        if w < img.shape[1] * 0.1 or h < img.shape[0] * 0.1: return None

        cropped = img[y:y+h, x:x+w]
        _, encoded_img = cv2.imencode(".png", cropped)
        return encoded_img.tobytes()

    except Exception as e:
        log(f"Crop Error: {e}")
        return None

async def process_images(event):
    if cv2 is None:
        log("Cannot process: OpenCV not loaded.")
        await ensure_dependencies()
        if cv2 is None: return

    files = js.window.selected_files
    if not files or files.length == 0:
        log("No files selected.")
        return

    # UI Reset
    document.getElementById("processing-section").classList.remove("hidden")
    document.getElementById("download-section").classList.add("hidden")
    document.getElementById("upload-section").classList.add("hidden")
    
    log(f"Processing {files.length} files...")
    
    zip_buffer = io.BytesIO()
    count = 0
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i in range(files.length):
            f = files.item(i)
            # Update progress bar
            pct = int(((i) / files.length) * 100)
            bar = document.getElementById("progress-bar")
            if bar:
                bar.style.width = f"{pct}%"
                bar.innerText = f"{pct}%"
            
            try:
                ab = await f.arrayBuffer()
                data = ab.to_bytes()
                res = crop_banknote(data)
                if res:
                    zf.writestr(f"{f.name}_cropped.png", res)
                    count += 1
                    log(f"Cropped {f.name}")
            except Exception as e:
                log(f"Failed {f.name}: {e}")
            
            await asyncio.sleep(0.01)

    # Finalize
    document.getElementById("progress-bar").style.width = "100%"
    document.getElementById("progress-bar").innerText = "100%"
    
    if count > 0:
        js_data = js.Uint8Array.new(len(zip_buffer.getvalue()))
        js_data.assign(zip_buffer.getvalue())
        
        document.getElementById("success-count").innerText = str(count)
        document.getElementById("processing-section").classList.add("hidden")
        document.getElementById("download-section").classList.remove("hidden")
        
        js.window.trigger_download(js_data, "cropped_banknotes.zip")
    else:
        log("No images cropped.")
        document.getElementById("processing-section").classList.add("hidden")
        document.getElementById("upload-section").classList.remove("hidden")

# --- Main ---

async def main():
    log("Main function started.")
    await ensure_dependencies()
    
    start_btn = document.getElementById("start-btn")
    if start_btn:
        start_btn.addEventListener("click", create_proxy(process_images))
        log("Button listener attached.")
    
    loader = document.getElementById("env-loader")
    if loader:
        loader.style.display = "none"
    
    log("System Initialized.")

if __name__ == "__main__":
    asyncio.ensure_future(main())
