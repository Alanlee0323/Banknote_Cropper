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
    log("Starting Setup...")
    loader_status = document.getElementById("loader-status") if document.getElementById("loader-status") else None
    
    try:
        # 1. Load Micropip first (safer dependency management)
        import micropip
        
        # 2. Update UI
        if loader_status: loader_status.innerText = "Installing OpenCV (this may take time)..."
        
        # 3. Explicitly install opencv-python via micropip if loadPackage fails or just as standard
        # Pyodide's loadPackage is fast for standard libs, but let's try micropip for robustness
        await micropip.install("opencv-python")
        await micropip.install("numpy")
        
        # 4. Import
        import cv2 as _cv2
        import numpy as _np
        cv2 = _cv2
        np = _np
        
        log(f"OpenCV Version: {cv2.__version__}")
        
        # 5. Hide Loader
        loader = document.getElementById("env-loader")
        if loader: 
            loader.style.opacity = "0"
            await asyncio.sleep(0.5)
            loader.style.display = "none"
            
        log("Engine Ready (Legacy Exact Mode).")
        return True

    except Exception as e:
        log(f"CRITICAL INIT ERROR: {e}")
        if loader_status:
            loader_status.innerText = f"Error: {e}"
            loader_status.style.color = "red"
        return False

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

# --- The "Old Script" Logic (Strict Port) ---
def process_and_get_preview(nparr):
    """
    執行 old_findcash.py 的完整邏輯。
    回傳: (preview_bytes, metadata_dict)
    """
    try:
        img_color = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
        if img_color is None: return None, None

        # 1. 讀取與轉換
        if len(img_color.shape) == 3 and img_color.shape[2] == 4:
            img_color = cv2.cvtColor(img_color, cv2.COLOR_BGRA2BGR)
        
        img_gray = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)
        
        # 2. 形態學處理 (Strict: Canny 100/250, Dilate 71x71)
        canny_edges = cv2.Canny(img_gray, 100, 250)
        dilate_kernel = np.ones((71, 71), np.uint8)
        canny_dilated = cv2.dilate(canny_edges, dilate_kernel)

        # 3. 連通域篩選 (Strict: Area > 100000)
        num_labels, labels_matrix, stats, _ = cv2.connectedComponentsWithStats(canny_dilated, connectivity=8)
        filtered_image = np.zeros_like(canny_dilated)
        min_area_threshold = 100000
        
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] >= min_area_threshold:
                filtered_image[labels_matrix == i] = 255
        
        # 4. 輪廓與最大外接矩形
        contours, _ = cv2.findContours(filtered_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return None, None # Not found

        max_contour = max(contours, key=cv2.contourArea)
        rect = cv2.minAreaRect(max_contour)
        (center, (w_rect, h_rect), angle) = rect
        
        # 5. 旋轉校正邏輯 (Strict Deskew)
        if w_rect < h_rect:
            angle += 90
            width, height = h_rect, w_rect
        else:
            width, height = w_rect, h_rect
            
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        (H, W) = img_color.shape[:2]
        abs_cos, abs_sin = abs(M[0, 0]), abs(M[0, 1])
        bound_w = int(H * abs_sin + W * abs_cos)
        bound_h = int(H * abs_cos + W * abs_sin)
        
        M[0, 2] += bound_w / 2 - center[0]
        M[1, 2] += bound_h / 2 - center[1]
        
        rotated_image = cv2.warpAffine(img_color, M, (bound_w, bound_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        
        # 6. 裁切 (Strict Padding)
        padding_val = 2
        x_center_rot, y_center_rot = bound_w / 2, bound_h / 2
        x1 = int(x_center_rot - width / 2 - padding_val)
        y1 = int(y_center_rot - height / 2 - padding_val)
        x2 = int(x_center_rot + width / 2 + padding_val)
        y2 = int(y_center_rot + height / 2 + padding_val)

        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(rotated_image.shape[1], x2), min(rotated_image.shape[0], y2)
        
        final_crop = rotated_image[y1:y2, x1:x2]
        
        if final_crop.size == 0: return None, None

        # Encode Preview (Return the actual result user will see)
        _, encoded_preview = cv2.imencode(".png", final_crop)
        
        # Store metadata for final processing (reconstruction)
        # We store the *raw inputs* for warpAffine so we can reproduce it later if needed,
        # OR we just trust the user input later.
        # For the "Edit" mode, we need the initial box on the *Original* image.
        # But wait, old_findcash uses Rotated Rect. JS Cropper only supports upright rects (mostly).
        # We will pass the BoundingRect of the MaxContour to JS for the "Edit" initial state.
        
        bx, by, bw, bh = cv2.boundingRect(max_contour)
        
        meta = {
            "found": True,
            "angle": angle,
            "cx": center[0], "cy": center[1],
            "w": width, "h": height, # Rotated dimensions
            # For JS Cropper Initial Box (Approximation)
            "init_x": bx, "init_y": by, "init_w": bw, "init_h": bh
        }
        
        return encoded_preview.tobytes(), meta

    except Exception as e:
        log(f"Process Error: {e}")
        return None, None

def on_py_analyze(event):
    try:
        js_buf = event.detail.buffer
        filename = event.detail.filename
        
        py_bytes = js_buf.to_bytes()
        nparr = np.frombuffer(py_bytes, np.uint8)
        
        preview_bytes, meta = process_and_get_preview(nparr)
        
        if preview_bytes:
            # Send Preview Blob back to JS (This fixes the "Blank Preview" bug)
            js_preview = js.Uint8Array.new(len(preview_bytes))
            js_preview.assign(preview_bytes)
            
            js.window.storeAnalysisResult(filename, to_js(meta), js_preview)
        else:
            # Failed to find cash
            js.window.storeAnalysisResult(filename, to_js({"found": False}), None)
            
    except Exception as e:
        log(f"Event Error: {e}")
        js.window.storeAnalysisResult(event.detail.filename, to_js({"found": False}), None)

# --- Finalize ---
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
        
        # If user didn't edit, we can re-run the logic OR use the passed parameters.
        # The JS now passes back whether it was "Modified" or "Original".
        # But to be safe and consistent, if it's "Original", we just re-run the strict logic.
        # If "Modified" (via Cropper.js), we use the simple crop.
        
        if meta.get("modified"):
            # User manually cropped it. Trust the user.
            nparr = np.frombuffer(py_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            x, y, w, h = int(meta.x), int(meta.y), int(meta.w), int(meta.h)
            cropped = img[y:y+h, x:x+w]
            
            # Shadow Upload (Manual Crop)
            h_img, w_img = img.shape[:2]
            cx, cy = (x+w/2)/w_img, (y+h/2)/h_img
            nw, nh = w/w_img, h/h_img
            label = f"0 {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}"
            asyncio.ensure_future(upload_to_r2(py_bytes, filename, label))
            
            if cropped.size > 0:
                _, encoded = cv2.imencode(".png", cropped)
                zf.writestr(f"{filename.split('.')[0]}_cropped.png", encoded.tobytes())

        else:
            # User approved the AI result. Re-run Strict Logic to get the exact deskewed result.
            # (We re-run instead of caching the preview to ensure highest quality from original bytes)
            nparr = np.frombuffer(py_bytes, np.uint8)
            
            # We reuse the function, but this time we need the result, not just preview
            preview_bytes, new_meta = process_and_get_preview(nparr)
            
            if preview_bytes:
                # Add to ZIP
                zf.writestr(f"{filename.split('.')[0]}_cropped.png", preview_bytes)
                
                # Shadow Upload (For Deskewed logic, calculating Original Box is hard)
                # We use the bounding rect of the rotated area as approximation for YOLO
                # Or we can use the 'init' values which were the boundingRect of contours
                if new_meta:
                    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    h_img, w_img = img.shape[:2]
                    # Use the contour bounding box for YOLO training data (it covers the object)
                    bx, by, bw, bh = new_meta['init_x'], new_meta['init_y'], new_meta['init_w'], new_meta['init_h']
                    cx, cy = (bx+bw/2)/w_img, (by+bh/2)/h_img
                    nw, nh = bw/w_img, bh/h_img
                    label = f"0 {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}"
                    asyncio.ensure_future(upload_to_r2(py_bytes, filename, label))

        js.window.finalizeDone()

    except Exception as e:
        log(f"Finalize Error: {e}")
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
