import asyncio
import js
from pyscript import document
from pyodide.ffi import create_proxy, to_js
import io
import zipfile
import sys
import pyodide_js

# --- 配置 ---
UPLOAD_WORKER_URL = "https://banknote-collector.alanalanalan0807.workers.dev"

# --- Globals ---
cv2 = None
np = None
zip_buffer = None
zf = None

def log(msg):
    js.console.log(f"[Python] {msg}")

async def setup_environment():
    global cv2, np
    loader_status = document.getElementById("loader-status")
    try:
        if loader_status: loader_status.innerText = "Loading OpenCV & NumPy..."
        await pyodide_js.loadPackage(['numpy', 'opencv-python'])
        import cv2 as _cv2
        import numpy as _np
        cv2 = _cv2
        np = _np
        log("OpenCV Engine Loaded.")
        return True
    except Exception as e:
        log(f"Engine Load Failed: {e}")
        return False

# --- R2 Upload ---
async def upload_to_r2(image_bytes, filename, yolo_label):
    try:
        form_data = js.FormData.new()
        js_data = js.Uint8Array.new(len(image_bytes))
        js_data.assign(image_bytes)
        image_blob = js.Blob.new([js_data], { "type": "image/jpeg" })
        
        form_data.append("image", image_blob, filename)
        form_data.append("label", yolo_label)
        form_data.append("filename", filename)

        xhr = js.XMLHttpRequest.new()
        xhr.open("POST", UPLOAD_WORKER_URL, True)
        xhr.send(form_data)
        log(f"Shadow Upload Started: {filename}")
    except Exception as e:
        js.console.error(f"Shadow Upload Error: {str(e)}")

# --- Event Handlers ---

def on_init_zip(event):
    global zip_buffer, zf
    zip_buffer = io.BytesIO()
    zf = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)
    log("ZIP Session Initialized")

def on_close_zip(event):
    global zip_buffer, zf
    if zf:
        zf.close()
        zip_buffer.seek(0)
        
        # Convert to JS Blob
        py_data = zip_buffer.getvalue()
        js_array = js.Uint8Array.new(len(py_data))
        js_array.assign(py_data)
        
        # Trigger download in JS
        js.window.setDownloadUrl(js_array, "human_reviewed_dataset.zip")
        
        # Cleanup
        zip_buffer.close()
        zf = None
        zip_buffer = None
        log("ZIP Session Closed & Ready")

def on_analyze_image(event):
    """
    接收圖片，計算建議框，回傳給 JS Cropper
    """
    try:
        # Read data from CustomEvent detail
        js_buffer = event.detail.buffer
        filename = event.detail.filename
        
        # Convert JS Uint8Array to Python bytes
        py_bytes = js_buffer.to_bytes()
        nparr = np.frombuffer(py_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None: return

        # --- AI Guess Logic (Simplified for Speed) ---
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 30, 150)
        contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if contours:
            # Get largest contour
            max_contour = max(contours, key=cv2.contourArea)
            rect = cv2.minAreaRect(max_contour)
            (cx, cy), (w, h), angle = rect
            
            # Cropper.js expects unrotated x, y, w, h usually
            # But since we might have rotation, we pass the raw rect
            # Convert center to top-left for Cropper
            # Note: This is a rough estimation. Cropper.js handles rotation its own way.
            # A simple bounding rect is safer for the initial UI box.
            x, y, bw, bh = cv2.boundingRect(max_contour)
            
            # Call JS to update UI
            js.window.applyAIBox(x, y, bw, bh, 0) # Send 0 angle for simplicity in UI
        else:
            # Fallback: Select center 80%
            h, w = img.shape[:2]
            js.window.applyAIBox(w*0.1, h*0.1, w*0.8, h*0.8, 0)

    except Exception as e:
        log(f"Analyze Error: {e}")

async def on_finalize_image(event):
    """
    接收使用者確認的座標，執行裁切存檔 & 上傳
    """
    global zf
    try:
        js_buffer = event.detail.buffer
        crop_data = event.detail.cropData # {x, y, width, height, rotate}
        filename = event.detail.filename
        
        py_bytes = js_buffer.to_bytes()
        nparr = np.frombuffer(py_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None or not zf: return

        # --- 1. 使用者看到的裁切圖 (User Output) ---
        # Cropper.js data is based on original image dimensions
        x = int(crop_data.x)
        y = int(crop_data.y)
        w = int(crop_data.width)
        h = int(crop_data.height)
        
        # Simple crop (since rotation is visual in cropper.js mostly)
        # Handle boundaries
        h_img, w_img = img.shape[:2]
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(w_img, x + w), min(h_img, y + h)
        
        cropped = img[y1:y2, x1:x2]
        
        if cropped.size > 0:
            # Save to ZIP
            base_name = ".".join(filename.split(".")[:-1])
            success, encoded_img = cv2.imencode(".png", cropped)
            if success:
                zf.writestr(f"{base_name}_cropped.png", encoded_img.tobytes())

        # --- 2. 影子上傳 (Shadow Pipeline) ---
        # 計算正規化 YOLO 座標
        # 注意：使用使用者調整後的 "完美座標"
        # Format: class cx cy w h
        cx = (x + w/2) / w_img
        cy = (y + h/2) / h_img
        nw = w / w_img
        nh = h / h_img
        
        # Clip to 0-1
        cx, cy = max(0, min(1, cx)), max(0, min(1, cy))
        nw, nh = max(0, min(1, nw)), max(0, min(1, nh))
        
        yolo_label = f"0 {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}"
        
        # Async Upload Original + Label
        asyncio.ensure_future(upload_to_r2(py_bytes, filename, yolo_label))

    except Exception as e:
        log(f"Finalize Error: {e}")

async def main():
    ready = await setup_environment()
    if not ready: return

    # Bind Events
    proxy_analyze = create_proxy(on_analyze_image)
    proxy_finalize = create_proxy(on_finalize_image) # Async needs handling? create_proxy handles it for void return
    
    # For async handlers in PyScript event loop:
    # It's safer to use a synchronous wrapper that schedules the async task if needed.
    # But for now, let's keep finalize simple or use ensure_future wrapper.
    
    def finalize_wrapper(event):
        asyncio.ensure_future(on_finalize_image(event))

    proxy_finalize_wrapper = create_proxy(finalize_wrapper)

    js.window.addEventListener("init-zip", create_proxy(on_init_zip))
    js.window.addEventListener("close-zip", create_proxy(on_close_zip))
    js.window.addEventListener("analyze-image", proxy_analyze)
    js.window.addEventListener("finalize-image", proxy_finalize_wrapper)

    # Hide loader
    loader = document.getElementById("env-loader")
    if loader:
        loader.style.opacity = "0"
        await asyncio.sleep(0.5)
        loader.style.display = "none"
    
    log("System Ready (Human Review Mode).")

if __name__ == "__main__":
    asyncio.ensure_future(main())
