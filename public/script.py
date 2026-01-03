import asyncio
import js
from pyscript import document
from pyodide.ffi import create_proxy, to_js
import io
import zipfile
import sys

# 從 GEMINI.md 獲取到的經驗：使用 pyodide_js 手動加載大型套件
import pyodide_js

def log(msg):
    js.console.log(f"[Python] {msg}")
    print(f"[Python] {msg}")
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
        
        # GEMINI.md Fix: 手動加載 package 確保穩定
        await pyodide_js.loadPackage(['numpy', 'opencv-python'])
        
        import cv2 as _cv2
        import numpy as _np
        cv2 = _cv2
        np = _np
        
        log("OpenCV Engine Loaded Successfully.")
        return True
    except Exception as e:
        log(f"Engine Load Failed: {e}")
        if loader_status:
            loader_status.innerText = f"Error: {e}"
        return False

def crop_banknote(image_bytes):
    """OpenCV 裁切邏輯"""
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
        
        # 過濾雜訊
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

    # 切換 UI
    document.getElementById("upload-section").classList.add("hidden")
    document.getElementById("processing-section").classList.remove("hidden")
    
    log(f"Processing {files.length} images...")
    
    # GEMINI.md Bug 4 Fix: 手動控制 ZIP 生命週期
    zip_buffer = io.BytesIO()
    zf = zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED)
    
    success_count = 0
    total = files.length

    for i in range(total):
        file = files.item(i)
        
        # 更新進度條
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
                zf.writestr(f"{base_name}_cropped.png", result)
                success_count += 1
                log(f"Done: {file.name}")
            else:
                log(f"Skipped: {file.name}")
        except Exception as e:
            log(f"Error {file.name}: {e}")
        
        await asyncio.sleep(0.01)

    # 結束處理
    zf.close() # Bug 4: 必須先 close 寫入中央目錄
    zip_buffer.seek(0)
    
    log(f"Finished. Successfully processed {success_count} images.")
    
    if success_count > 0:
        # GEMINI.md Bug 3 Fix: 使用 js.Blob 避免記憶體拷貝問題
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
    # 執行環境設定
    ready = await setup_environment()
    if not ready:
        log("System failed to initialize.")
        return

    # 綁定按鈕
    start_btn = document.getElementById("start-btn")
    if start_btn:
        start_btn.addEventListener("click", create_proxy(process_all_files))
        log("Event listeners attached.")

    # 隱藏加載畫面
    loader = document.getElementById("env-loader")
    if loader:
        loader.style.opacity = "0"
        await asyncio.sleep(0.5)
        loader.style.display = "none"
    
    log("System Ready.")

if __name__ == "__main__":
    asyncio.ensure_future(main())