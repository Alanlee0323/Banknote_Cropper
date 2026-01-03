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
    try:
        await pyodide_js.loadPackage(['numpy', 'opencv-python'])
        import cv2 as _cv2
        import numpy as _np
        cv2 = _cv2
        np = _np
        # Remove loader
        loader = document.getElementById("env-loader")
        if loader: loader.style.display = "none"
        log("Engine Ready.")
    except Exception as e:
        log(f"Init Error: {e}")

# --- Shadow Pipeline ---
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
    except Exception as e:
        js.console.error(f"Upload Error: {str(e)}")

# --- Logic 1: Analysis (Pre-calc) ---
def analyze_image(nparr):
    try:
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None: return None

        # Standard CV Logic
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 30, 150)
        
        # Dilate to connect components
        kernel = np.ones((5, 5), np.uint8) # Smaller kernel for speed in preview
        dilated = cv2.dilate(edged, kernel, iterations=2)
        
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            h, w = img.shape[:2]
            return {"x": w*0.1, "y": h*0.1, "w": w*0.8, "h": h*0.8, "angle": 0}

        max_cnt = max(contours, key=cv2.contourArea)
        rect = cv2.minAreaRect(max_cnt)
        (cx, cy), (w, h), angle = rect
        
        # Convert center to top-left for JS
        # This is an approximation for initial box. CropperJS handles rotation better.
        # We return the bounding box of the rotated rect to ensure it covers everything.
        x, y, bw, bh = cv2.boundingRect(max_cnt)
        
        return {
            "x": x, "y": y, "w": bw, "h": bh, "angle": 0 # Start with 0 rotation for easier UI
        }
    except Exception as e:
        log(f"Analyze Error: {e}")
        return None

def on_py_analyze(event):
    try:
        js_buf = event.detail.buffer
        filename = event.detail.filename
        
        py_bytes = js_buf.to_bytes()
        nparr = np.frombuffer(py_bytes, np.uint8)
        
        result = analyze_image(nparr)
        
        # Fallback
        if not result: result = {"x":0, "y":0, "w":100, "h":100, "angle":0}
        
        # Callback to JS
        js.window.storeAnalysisResult(filename, to_js(result))
        
    except Exception as e:
        log(f"Event Error: {e}")

# --- Logic 2: Final Processing ---
def on_init_zip(event):
    global zip_buffer, zf
    zip_buffer = io.BytesIO()
    zf = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)

async def on_process_item(event):
    global zf
    try:
        js_buf = event.detail.buffer
        filename = event.detail.filename
        meta = event.detail.meta
        
        py_bytes = js_buf.to_bytes()
        nparr = np.frombuffer(py_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img and zf:
            # 1. Crop for User
            x, y, w, h = int(meta.x), int(meta.y), int(meta.w), int(meta.h)
            h_img, w_img = img.shape[:2]
            
            # Boundary check
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(w_img, x + w), min(h_img, y + h)
            
            cropped = img[y1:y2, x1:x2]
            
            if cropped.size > 0:
                base = ".".join(filename.split(".")[:-1])
                _, encoded = cv2.imencode(".png", cropped)
                zf.writestr(f"{base}_cropped.png", encoded.tobytes())
            
            # 2. Shadow Upload (Original + Normalized Label)
            cx = (x + w/2) / w_img
            cy = (y + h/2) / h_img
            nw = w / w_img
            nh = h / h_img
            label = f"0 {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}"
            
            asyncio.ensure_future(upload_to_r2(py_bytes, filename, label))

        # Signal JS to continue
        js.window.finalizeDone()

    except Exception as e:
        log(f"Process Item Error: {e}")
        js.window.finalizeDone()

def on_close_zip(event):
    global zip_buffer, zf
    if zf:
        zf.close()
        zip_buffer.seek(0)
        data = zip_buffer.getvalue()
        
        js_arr = js.Uint8Array.new(len(data))
        js_arr.assign(data)
        js.window.setDownloadUrl(js_arr, "dataset.zip")
        
        zip_buffer.close()
        zf = None

async def main():
    await setup_environment()
    
    # Event Bindings
    js.window.addEventListener("py-analyze", create_proxy(on_py_analyze))
    js.window.addEventListener("py-init-zip", create_proxy(on_init_zip))
    js.window.addEventListener("py-close-zip", create_proxy(on_close_zip))
    
    # Async wrapper for process item
    def process_wrapper(e):
        asyncio.ensure_future(on_process_item(e))
        
    js.window.addEventListener("py-process-item", create_proxy(process_wrapper))

if __name__ == "__main__":
    asyncio.ensure_future(main())