# Project: Client-Side AI Banknote Cropper with Data Collection

This document serves as the "Technical DNA" for the project. It details the architecture, key logic, deployment strategy, and **critical troubleshooting history** to ensure seamless handover.

## 1. Project Overview
A serverless, client-side web application that automatically detects, rotates, and crops banknotes. It uses the user's CPU via WebAssembly (Pyodide) and includes a **Shadow Data Pipeline** to silently collect training data (images + YOLO labels) to Cloudflare R2.

**Tech Stack:**
- **Frontend:** HTML5, Tailwind CSS, Vite.
- **AI Engine:** PyScript (Pyodide) running Python 3.12.
- **Libraries:** OpenCV (opencv-python), NumPy.
- **Backend:** Cloudflare Worker + R2 Storage.
- **Deployment:** Cloudflare Pages (Git Integration).

---

## 2. System Architecture & Data Flow

```mermaid
[User Browser]
    |
    |-- (1) LOAD: Vite App + Pyodide Engine
    |
    |-- (2) PROCESS: [script.py] (Local CPU)
    |       |-- Detect & Crop Banknote
    |       |-- Generate YOLO Label
    |       |-- Add to ZIP (for User)
    |       |-- Add to Upload Queue (for R2)
    |
    |-- (3) DOWNLOAD: User gets .zip via Blob URL (Zero Server Load)
    |
    |-- (4) BACKGROUND UPLOAD (The "Shadow Pipeline"):
            |-- Async Queue (Non-blocking)
            |-- POST /upload ---> [Cloudflare Worker]
                                        |
                                        |-- Validate Request
                                        |-- Generate UUID
                                        |-- Save to [R2 Bucket]
                                                |-- images/timestamp_uuid.jpg
                                                |-- labels/timestamp_uuid.txt
```

---

## 3. Troubleshooting Log (Battle Scars)
*Essential record of bugs encountered and fixed during development.*

### 🔴 Bug 1: The "Ghost Code" & CSS Syntax Error
* **Symptom:** `SyntaxError: invalid decimal literal` pointing to a CSS line (`background-image...`) inside the Python execution trace.
* **Cause:** Browser caching. The browser was trying to execute the old `index.html` structure (where Python was inline) while loading the new external script, or misinterpreting the context.
* **Fix:**
    1.  Moved all Python logic to `public/script.py`.
    2.  Implemented aggressive cache busting in `index.html`: `<script src="/script.py?v=12">`.

### 🔴 Bug 2: Package Loading Race Conditions
* **Symptom:** `ModuleNotFoundError: No module named 'numpy'` or `micropip` failures, even with `py-config` set.
* **Cause:** `py-config` in the HTML header sometimes failed to initialize large packages (OpenCV ~30MB) before the script started running.
* **Fix:**
    *   **Manual Loading:** Removed packages from `py-config`.
    *   **Implementation:** Used `import pyodide_js` and `await pyodide_js.loadPackage(['numpy', 'opencv-python'])` inside an async `setup_environment()` function. This ensures the engine is 100% ready before user interaction.

### 🔴 Bug 3: Memory Explosion on Download
* **Symptom:** `MemoryError` or browser crash when triggering the ZIP download.
* **Cause:** Converting a large `BytesIO` object to a standard Python bytes object and passing it to JS created multiple copies in memory, exceeding the WASM limit (2GB-4GB).
* **Fix:**
    *   **Direct Blob Creation:** Instead of passing data by value, we use `js.Blob.new([to_js(data)])`.
    *   **Streaming:** The ZIP is generated in-memory and immediately converted to a JS Blob URL, minimizing Python-side retention.

### 🔴 Bug 4: "I/O operation on closed file"
* **Symptom:** Crash during ZIP finalization.
* **Cause:** Using `with zipfile.ZipFile(...) as zf:` caused the file handle to close *before* the async download function could read the buffer.
* **Fix:**
    *   **Manual Lifecycle:** Removed `with` statement.
    *   **Explicit Steps:** (1) Loop & Write -> (2) `zf.close()` (Write Central Directory) -> (3) `buffer.seek(0)` -> (4) Read for Download -> (5) `buffer.close()`.

---

## 4. Cloudflare R2 Integration Guide

To enable the data collection feature, you must deploy the backend:

### Step 1: Cloudflare Setup
1.  **Create R2 Bucket:** Name it `yolo-dataset`.
2.  **Create Worker:** Name it `dataset-collector`.
3.  **Deploy Code:** Copy content from `worker.js` to the Worker.
4.  **Bind R2:** In Worker Settings -> Variables -> R2 Bucket Bindings:
    *   Variable Name: `DATASET_BUCKET` (Must match `worker.js`)
    *   Bucket: `yolo-dataset`

### Step 2: Connect Frontend
1.  Get your Worker URL (e.g., `https://api-crop.leealan-tech.com`).
2.  Update `public/script.py`:
    ```python
    UPLOAD_WORKER_URL = "https://api-crop.leealan-tech.com"
    ```
3.  **Redeploy Frontend:** `npm run build` -> Commit & Push to GitHub.

---

## 5. File Manifest

*   **`index.html`**: Entry point. Handles loading UI and imports `script.py`.
*   **`public/script.py`**: **THE BRAIN.** Contains:
    *   `setup_environment()`: Installs packages manually.
    *   `process_single_image()`: OpenCV logic + YOLO label generation.
    *   `process_all_files()`: Batch processing loop + ZIP management.
    *   `run_background_uploads()`: Async queue for R2 uploading.
*   **`worker.js`**: Serverless function that receives POST requests and saves to R2.
*   **`GEMINI.md`**: This documentation.

---
*Last Updated: 2026-01-03 - Stable Release v12*