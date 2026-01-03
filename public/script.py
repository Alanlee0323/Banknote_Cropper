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

# --- UI Helpers ---
def log(msg):
    # 簡單的 console log，不再依賴舊的 log-container
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

# --- Shadow Pipeline (保持不變) ---
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
        js.console.error(f"Shadow Upload Error: {str(e)}")

# --- Core Logic ---
def process_image_data(image_bytes):
    """
    回傳: (cropped_bytes, yolo_label, metadata_dict)
    """
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img_color = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
        
        if img_color is None: return None, None, None

        if len(img_color.shape) == 3 and img_color.shape[2] == 4:
            img_color = cv2.cvtColor(img_color, cv2.COLOR_BGRA2BGR)
        
        orig_h, orig_w = img_color.shape[:2]
        img_gray = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)
        
        # CV Logic
        canny_edges = cv2.Canny(img_gray, 100, 250)
        dilate_kernel = np.ones((71, 71), np.uint8)
        canny_dilated = cv2.dilate(canny_edges, dilate_kernel)

        num_labels, labels_matrix, stats, _ = cv2.connectedComponentsWithStats(canny_dilated, connectivity=8)
        filtered_image = np.zeros_like(canny_dilated)
        min_area_threshold = 100000
        
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] >= min_area_threshold:
                filtered_image[labels_matrix == i] = 255

        contours, _ = cv2.findContours(filtered_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours: return None, None, None
        
        max_contour = max(contours, key=cv2.contourArea)

        # Deskew Logic
        rect = cv2.minAreaRect(max_contour)
        (center_x, center_y), (w_rect, h_rect), angle = rect

        # YOLO Label Calc
        x, y, w, h = cv2.boundingRect(max_contour)
        yolo_cx = (x + w / 2) / orig_w
        yolo_cy = (y + h / 2) / orig_h
        yolo_w = w / orig_w
        yolo_h = h / orig_h
        yolo_label = f"0 {yolo_cx:.6f} {yolo_cy:.6f} {yolo_w:.6f} {yolo_h:.6f}"

        # Rotation
        if w_rect < h_rect:
            angle += 90
            width, height = h_rect, w_rect
        else:
            width, height = w_rect, h_rect

        M = cv2.getRotationMatrix2D((center_x, center_y), angle, 1.0)
        abs_cos = abs(M[0, 0])
        abs_sin = abs(M[0, 1])
        bound_w = int(orig_h * abs_sin + orig_w * abs_cos)
        bound_h = int(orig_h * abs_cos + orig_w * abs_sin)

        M[0, 2] += bound_w / 2 - center_x
        M[1, 2] += bound_h / 2 - center_y

        rotated_image = cv2.warpAffine(img_color, M, (bound_w, bound_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

        new_cx, new_cy = bound_w / 2, bound_h / 2
        padding_val = 2

        x1 = int(new_cx - width / 2 - padding_val)
        y1 = int(new_cy - height / 2 - padding_val)
        x2 = int(new_cx + width / 2 + padding_val)
        y2 = int(new_cy + height / 2 + padding_val)

        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(rotated_image.shape[1], x2), min(rotated_image.shape[0], y2)

        final_crop = rotated_image[y1:y2, x1:x2]
        if final_crop.size == 0: return None, None, None

        _, encoded_crop = cv2.imencode(".png", final_crop)
        
        # Metadata for UI
        meta = {
            "orig_w": orig_w,
            "orig_h": orig_h,
            "angle": angle if angle < 45 else angle - 90 # Adjust angle for display human-readability
        }
        
        return encoded_crop.tobytes(), yolo_label, meta

    except Exception as e:
        log(f"Process error: {e}")
        return None, None, None

async def process_all_files(event):
    files = js.window.selected_files
    if not files or files.length == 0: return

    # UI Setup
    log(f"Processing {files.length} images...")
    
    zip_buffer = io.BytesIO()
    zf = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)
    
    success_count = 0
    total = files.length
    
    # UI Elements
    status_text = document.getElementById("status-text")
    progress_bar = document.getElementById("progress-bar")
    progress_percent = document.getElementById("progress-percent")
    processed_count = document.getElementById("processed-count")
    
    for i in range(total):
        file = files.item(i)
        
        # Update UI Progress
        pct = int(((i) / total) * 100)
        if progress_bar: progress_bar.style.width = f"{pct}%"
        if progress_percent: progress_percent.innerText = f"{pct}%"
        if processed_count: processed_count.innerText = f"{i}/{total}"
        if status_text: status_text.innerText = f"Processing {file.name}..."
        
        try:
            array_buffer = await file.arrayBuffer()
            original_data = array_buffer.to_bytes()
            
            # Process
            cropped_bytes, real_yolo_label, meta = process_image_data(original_data)
            
            if cropped_bytes and real_yolo_label:
                # Update Live Preview (Call JS helper)
                # Need to convert bytes to JS Uint8Array
                js_orig = js.Uint8Array.new(len(original_data))
                js_orig.assign(original_data)
                
                js_crop = js.Uint8Array.new(len(cropped_bytes))
                js_crop.assign(cropped_bytes)
                
                # Add filename to meta
                meta_js = to_js(meta)
                meta_js.filename = file.name
                
                js.window.update_preview(js_orig, js_crop, meta_js)
                
                # Save & Upload
                base_name = ".".join(file.name.split(".")[:-1])
                img_name_for_zip = f"{base_name}_cropped.png"
                zf.writestr(img_name_for_zip, cropped_bytes)
                asyncio.ensure_future(upload_to_r2(original_data, file.name, real_yolo_label))
                
                success_count += 1
            else:
                log(f"Skipped: {file.name}")
        except Exception as e:
            log(f"Error {file.name}: {e}")
        
        # Small sleep to let UI update render
        await asyncio.sleep(0.05)

    # Finalize
    zf.close()
    zip_buffer.seek(0)
    
    # UI Completion State
    if progress_bar: progress_bar.style.width = "100%"
    if progress_percent: progress_percent.innerText = "100%"
    if processed_count: processed_count.innerText = f"{total}/{total}"
    if status_text: status_text.innerText = "Processing complete"
    
    if success_count > 0:
        zip_data = zip_buffer.getvalue()
        js_array = js.Uint8Array.new(len(zip_data))
        js_array.assign(zip_data)
        
        # Trigger Download
        js.window.trigger_download(js_array, "banknote_dataset.zip")
    
    zip_buffer.close()

async def main():
    ready = await setup_environment()
    if not ready: return

    # Listen for custom event from JS
    # We use a proxy to bind the async handler
    handler = create_proxy(process_all_files)
    js.window.addEventListener("start-processing", handler)

    # Hide loader
    loader = document.getElementById("env-loader")
    if loader:
        loader.style.opacity = "0"
        await asyncio.sleep(0.5)
        loader.style.display = "none"
    
    log("System Ready.")

if __name__ == "__main__":
    asyncio.ensure_future(main())