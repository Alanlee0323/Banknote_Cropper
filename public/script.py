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

def log(msg):
    js.console.log(f"[Python] {msg}")
    log_container = document.getElementById("log-container")
    if log_container:
        entry = document.createElement("div")
        entry.innerText = f">> {msg}"
        log_container.appendChild(entry)
        log_container.scrollTop = log_container.scrollHeight

cv2 = None
np = None

async def setup_environment():
    global cv2, np
    log("Initializing AI Engine...")
    loader_status = document.getElementById("loader-status")
    try:
        if loader_status:
            loader_status.innerText = "Loading OpenCV & NumPy (~30MB)..."
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
        
        def on_load(event):
            if xhr.status >= 200 and xhr.status < 300:
                js.console.log(f"Shadow Upload Success: {filename}")
            else:
                js.console.error(f"Shadow Upload Failed [{xhr.status}]")

        xhr.onload = create_proxy(on_load)
        xhr.send(form_data)
    except Exception as e:
        js.console.error(f"Shadow Upload Error: {str(e)}")

def process_image_data(image_bytes):
    """
    【移植版】整合 old_findcash.py 的強力邏輯：
    1. 形態學膨脹 (71x71)
    2. 連通域分析
    3. 旋轉校正 (Deskew)
    4. Padding
    """
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img_color = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
        
        if img_color is None: return None, None

        # 處理 Alpha 通道
        if len(img_color.shape) == 3 and img_color.shape[2] == 4:
            img_color = cv2.cvtColor(img_color, cv2.COLOR_BGRA2BGR)
        
        img_gray = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)
        
        # --- 2. 形態學處理 (移植自 old_findcash.py) ---
        canny_edges = cv2.Canny(img_gray, 100, 250)
        
        # Kernel 71x71 (注意：在瀏覽器中這可能會稍微慢一點，但效果最好)
        dilate_kernel = np.ones((71, 71), np.uint8)
        canny_dilated = cv2.dilate(canny_edges, dilate_kernel)

        # 連通域分析
        num_labels, labels_matrix, stats, _ = cv2.connectedComponentsWithStats(canny_dilated, connectivity=8)
        filtered_image = np.zeros_like(canny_dilated)
        min_area_threshold = 100000 # 與舊代碼一致
        
        # 篩選大區塊
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] >= min_area_threshold:
                filtered_image[labels_matrix == i] = 255

        # --- 3. 尋找最大輪廓 ---
        contours, _ = cv2.findContours(filtered_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return None, None
        
        max_contour = max(contours, key=cv2.contourArea)

        # --- 4. 旋轉與裁切邏輯 ---
        # 計算最小外接矩形 (Rotated Rect)
        rect = cv2.minAreaRect(max_contour)
        (center_x, center_y), (w_rect, h_rect), angle = rect

        # --- 計算給 R2 的 YOLO 標籤 (基於原圖的直立外框) ---
        # YOLO 只能吃直立框，所以我們取 Rotated Rect 的 Bounding Rect
        # 這會比單純 boundingRect(max_contour) 更貼合一點，但也差不多
        x, y, w, h = cv2.boundingRect(max_contour)
        img_h, img_w = img_color.shape[:2]
        
        # 正規化 YOLO 座標
        yolo_cx = (x + w / 2) / img_w
        yolo_cy = (y + h / 2) / img_h
        yolo_w = w / img_w
        yolo_h = h / img_h
        yolo_label = f"0 {yolo_cx:.6f} {yolo_cy:.6f} {yolo_w:.6f} {yolo_h:.6f}"

        # --- 進行旋轉裁切 (給使用者的成品) ---
        if w_rect < h_rect:
            angle += 90
            width, height = h_rect, w_rect
        else:
            width, height = w_rect, h_rect

        # 旋轉矩陣
        M = cv2.getRotationMatrix2D((center_x, center_y), angle, 1.0)
        
        # 計算旋轉後的新邊界，避免切到角
        abs_cos = abs(M[0, 0])
        abs_sin = abs(M[0, 1])
        bound_w = int(img_h * abs_sin + img_w * abs_cos)
        bound_h = int(img_h * abs_cos + img_w * abs_sin)

        M[0, 2] += bound_w / 2 - center_x
        M[1, 2] += bound_h / 2 - center_y

        rotated_image = cv2.warpAffine(img_color, M, (bound_w, bound_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

        # 計算裁切座標 (中心點在新圖的中心)
        new_cx, new_cy = bound_w / 2, bound_h / 2
        padding_val = 2 # 移植自 old_findcash.py 的預設值

        x1 = int(new_cx - width / 2 - padding_val)
        y1 = int(new_cy - height / 2 - padding_val)
        x2 = int(new_cx + width / 2 + padding_val)
        y2 = int(new_cy + height / 2 + padding_val)

        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(rotated_image.shape[1], x2), min(rotated_image.shape[0], y2)

        final_crop = rotated_image[y1:y2, x1:x2]
        
        if final_crop.size == 0: return None, None

        _, encoded_crop = cv2.imencode(".png", final_crop)
        return encoded_crop.tobytes(), yolo_label

    except Exception as e:
        log(f"Process error: {e}")
        return None, None

async def process_all_files(event):
    files = js.window.selected_files
    if not files or files.length == 0: return

    document.getElementById("upload-section").classList.add("hidden")
    document.getElementById("processing-section").classList.remove("hidden")
    
    log(f"Processing {files.length} images...")
    
    zip_buffer = io.BytesIO()
    zf = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)
    
    success_count = 0
    total = files.length
    
    for i in range(total):
        file = files.item(i)
        progress = int((i / total) * 100)
        bar = document.getElementById("progress-bar")
        if bar:
            bar.style.width = f"{progress}%"
            bar.innerText = f"{progress}%"
        
        try:
            array_buffer = await file.arrayBuffer()
            original_data = array_buffer.to_bytes()
            
            # 使用新移植的強力邏輯
            cropped_bytes, real_yolo_label = process_image_data(original_data)
            
            if cropped_bytes and real_yolo_label:
                base_name = ".".join(file.name.split(".")[:-1])
                img_name_for_zip = f"{base_name}_cropped.png"
                
                # A. 寫入旋轉校正後的圖
                zf.writestr(img_name_for_zip, cropped_bytes)
                
                # B. 上傳原圖 + 直立框標籤
                asyncio.ensure_future(upload_to_r2(original_data, file.name, real_yolo_label))
                
                success_count += 1
                log(f"Done: {file.name}")
            else:
                log(f"Skipped: {file.name}")
        except Exception as e:
            log(f"Error {file.name}: {e}")
        
        await asyncio.sleep(0.01)

    zf.close()
    zip_buffer.seek(0)
    
    if success_count > 0:
        log(f"Success! Processed {success_count} images.")
        zip_data = zip_buffer.getvalue()
        js_array = js.Uint8Array.new(len(zip_data))
        js_array.assign(zip_data)
        
        document.getElementById("success-count").innerText = str(success_count)
        document.getElementById("processing-section").classList.add("hidden")
        document.getElementById("download-section").classList.remove("hidden")
        
        js.window.trigger_download(js_array, "cropped_banknotes.zip")
    else:
        log("No images were cropped.")
        document.getElementById("processing-section").classList.add("hidden")
        document.getElementById("upload-section").classList.remove("hidden")
    
    zip_buffer.close()

async def main():
    ready = await setup_environment()
    if not ready: return

    start_btn = document.getElementById("start-btn")
    if start_btn:
        start_btn.addEventListener("click", create_proxy(process_all_files))
        log("Ready (Enhanced Engine).")

    loader = document.getElementById("env-loader")
    if loader:
        loader.style.opacity = "0"
        await asyncio.sleep(0.5)
        loader.style.display = "none"
    
    log("System Ready.")

if __name__ == "__main__":
    asyncio.ensure_future(main())
