import asyncio
import js
from pyscript import document, display
from pyodide.ffi import create_proxy, to_js
import io
import zipfile

print("DEBUG: script.py is loading...")

# Late import for cv2 to allow manual install if py-config fails
cv2 = None
np = None

async def ensure_dependencies():
    global cv2, np
    loader_status = document.getElementById("loader-status")
    try:
        import cv2 as _cv2
        import numpy as _np
        cv2 = _cv2
        np = _np
    except ImportError:
        import micropip
        if loader_status:
            loader_status.innerText = "Downloading OpenCV Engine (~30MB)..."
        print("Installing opencv-python...")
        await micropip.install("opencv-python")
        import cv2 as _cv2
        import numpy as _np
        cv2 = _cv2
        np = _np
    
    if loader_status:
        loader_status.innerText = "Finalizing..."
    print("Dependencies loaded successfully")

# --- UI Helpers ---

def log_to_ui(message, is_error=False):
    """Logs a message to the UI console."""
    print(message)
    log_container = document.getElementById("log-container")
    if log_container:
        entry = document.createElement("div")
        entry.innerText = f">> {message}"
        if is_error:
            entry.classList.add("text-red-500")
        log_container.appendChild(entry)
        log_container.scrollTop = log_container.scrollHeight

def update_progress(current, total, status_msg=""):
    """Updates the progress bar and status text."""
    percentage = int((current / total) * 100) if total > 0 else 0
    
    progress_bar = document.getElementById("progress-bar")
    progress_text = document.getElementById("progress-text")
    status_text = document.getElementById("status-text")
    
    if progress_bar:
        progress_bar.style.width = f"{percentage}%"
        progress_bar.innerText = f"{percentage}%"
    
    if progress_text:
        progress_text.innerText = f"{percentage}%"
        
    if status_text and status_msg:
        status_text.innerText = status_msg

def show_section(section_id):
    """Toggles visibility of UI sections."""
    sections = ["upload-section", "processing-section", "download-section"]
    for sec in sections:
        el = document.getElementById(sec)
        if el:
            if sec == section_id:
                el.classList.remove("hidden")
            else:
                el.classList.add("hidden")

# --- Core Logic ---

def crop_banknote(image_bytes):
    """
    Decodes an image from bytes, finds the largest contour (assumed banknote),
    and returns the cropped image encoded as PNG bytes.
    """
    if cv2 is None or np is None:
        return None
        
    try:
        # Decode image
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            return None

        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Canny edge detection
        edged = cv2.Canny(blurred, 30, 150)
        
        # Find contours
        contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return None

        # Sort contours by area, keep largest
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        largest_contour = contours[0]
        
        # Get bounding box
        x, y, w, h = cv2.boundingRect(largest_contour)
        
        # Filter small noise
        img_h, img_w = img.shape[:2]
        if w < img_w * 0.1 or h < img_h * 0.1:
            return None

        # Crop
        cropped = img[y:y+h, x:x+w]
        
        # Encode back to PNG
        _, encoded_img = cv2.imencode(".png", cropped)
        return encoded_img.tobytes()

    except Exception as e:
        log_to_ui(f"Error cropping image: {str(e)}", is_error=True)
        return None

async def process_images(event):
    """Main event handler for processing."""
    
    # Ensure deps are loaded (if click happens fast)
    if cv2 is None:
        log_to_ui("Waiting for dependencies to initialize...")
        await ensure_dependencies()

    files = js.window.selected_files
    if not files or files.length == 0:
        log_to_ui("No files selected!", is_error=True)
        return

    show_section("processing-section")
    total_files = files.length
    log_to_ui(f"Starting processing of {total_files} files...")
    
    zip_buffer = io.BytesIO()
    success_count = 0
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for i in range(total_files):
            file = files.item(i)
            file_name = file.name
            
            update_progress(i, total_files, f"Processing {file_name}...")
            
            try:
                array_buffer = await file.arrayBuffer()
                data = array_buffer.to_bytes()
                
                cropped_bytes = crop_banknote(data)
                
                if cropped_bytes:
                    base_name = ".".join(file_name.split(".")[:-1])
                    new_name = f"{base_name}_cropped.png"
                    zip_file.writestr(new_name, cropped_bytes)
                    success_count += 1
                    log_to_ui(f"Cropped: {file_name}")
                else:
                    log_to_ui(f"Skipped: {file_name}")
                    
            except Exception as e:
                log_to_ui(f"Error processing {file_name}: {str(e)}", is_error=True)
            
            await asyncio.sleep(0.01)

    update_progress(total_files, total_files, "Finalizing ZIP archive...")
    
    if success_count > 0:
        log_to_ui(f"Processing complete. {success_count}/{total_files} images cropped.")
        zip_data = zip_buffer.getvalue()
        js_array = js.Uint8Array.new(len(zip_data))
        js_array.assign(zip_data)
        
        document.getElementById("success-count").innerText = str(success_count)
        show_section("download-section")
        js.window.trigger_download(js_array, "cropped_banknotes.zip")
    else:
        log_to_ui("No images were successfully cropped.", is_error=True)
        document.getElementById("success-count").innerText = "0"
        show_section("download-section")

# --- Initialization ---

async def main():
    # 1. Load dependencies first
    await ensure_dependencies()
    
    # 2. Setup event listeners
    start_btn = document.getElementById("start-btn")
    if start_btn:
        on_click_proxy = create_proxy(process_images)
        start_btn.addEventListener("click", on_click_proxy)
    
    # 3. Hide loader
    loader = document.getElementById("env-loader")
    if loader:
        loader.style.display = "none"
    
    log_to_ui("System Ready (OpenCV loaded)")

if __name__ == "__main__":
    # In PyScript, we can use top-level await if it's a module, 
    # but here we'll use asyncio to run the main coro.
    asyncio.ensure_future(main())