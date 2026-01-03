import asyncio
import js
from pyscript import document, display
from pyodide.ffi import create_proxy, to_js
import cv2
import numpy as np
import io
import zipfile

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
    percentage = int((current / total) * 100)
    
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
    Returns None if no valid contour is found or error occurs.
    """
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
        
        # Edge detection (Canny) - Auto threshold might be better but let's try standard first
        # Or simple thresholding
        # _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Canny is often robust for banknotes
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
        
        # Filter small noise (if the largest thing is tiny, it's probably not a banknote)
        img_h, img_w = img.shape[:2]
        if w < img_w * 0.1 or h < img_h * 0.1:
            return None # Too small

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
    
    # 1. Setup UI
    files = js.window.selected_files
    if not files or files.length == 0:
        log_to_ui("No files selected!", is_error=True)
        return

    show_section("processing-section")
    total_files = files.length
    log_to_ui(f"Starting processing of {total_files} files...")
    
    # Prepare ZIP in memory
    zip_buffer = io.BytesIO()
    
    success_count = 0
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for i in range(total_files):
            file = files.item(i)
            file_name = file.name
            
            update_progress(i, total_files, f"Processing {file_name}...")
            
            try:
                # Read file content from JS
                array_buffer = await file.arrayBuffer()
                # Convert JS ArrayBuffer to Python bytes
                data = array_buffer.to_bytes()
                
                # Process
                cropped_bytes = crop_banknote(data)
                
                if cropped_bytes:
                    # Use original name or add suffix
                    # Let's clean the name: remove extension, add .png
                    base_name = ".".join(file_name.split(".")[:-1])
                    new_name = f"{base_name}_cropped.png"
                    
                    zip_file.writestr(new_name, cropped_bytes)
                    success_count += 1
                    log_to_ui(f"Cropped: {file_name}")
                else:
                    log_to_ui(f"Skipped (No banknote found): {file_name}")
                    
            except Exception as e:
                log_to_ui(f"Error processing {file_name}: {str(e)}", is_error=True)
            
            # Yield control to UI loop
            await asyncio.sleep(0.01)

    update_progress(total_files, total_files, "Finalizing ZIP archive...")
    
    # 2. Trigger Download
    if success_count > 0:
        log_to_ui(f"Processing complete. {success_count}/{total_files} images cropped.")
        
        # Prepare final ZIP bytes
        zip_data = zip_buffer.getvalue()
        
        # Create JS Uint8Array from Python bytes
        js_array = js.Uint8Array.new(len(zip_data))
        js_array.assign(zip_data)
        
        # Update Done Section
        document.getElementById("success-count").innerText = str(success_count)
        show_section("download-section")
        
        # Hook up the JS download trigger
        js.window.trigger_download(js_array, "cropped_banknotes.zip")
        
    else:
        log_to_ui("Processing finished but no images were successfully cropped.", is_error=True)
        # Maybe show an error state or let them go back?
        # For now, just show download section but maybe with 0 count
        document.getElementById("success-count").innerText = "0"
        show_section("download-section")

# --- Initialization ---

def setup():
    start_btn = document.getElementById("start-btn")
    if start_btn:
        on_click_proxy = create_proxy(process_images)
        start_btn.addEventListener("click", on_click_proxy)
    
    # Signal readiness
    loader = document.getElementById("env-loader")
    if loader:
        loader.style.display = "none"
    
    log_to_ui("System Ready (OpenCV loaded)")

if __name__ == "__main__":
    setup()
