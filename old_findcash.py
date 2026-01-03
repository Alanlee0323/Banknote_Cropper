import cv2
import numpy as np
import os

# --- 設定輸入和輸出資料夾路徑 ---
input_folder = r"C:\Users\alana\Downloads\S-20251223T153602Z-1-001\S\紙鈔"
output_folder = r"C:\Users\alana\Downloads\S-20251223T153602Z-1-001\S\紙鈔\1" 

# 檢查輸入資料夾是否存在
if not os.path.exists(input_folder):
    print(f"錯誤：輸入資料夾 '{input_folder}' 不存在。請檢查路徑。")
    exit()

# 創建輸出資料夾
if not os.path.exists(output_folder):
    os.makedirs(output_folder)
    print(f"輸出資料夾 '{output_folder}' 已建立。")

def process_image_and_crop(image_path, padding_val=5):
    """
    【最終生產版本】：整合了強力形態學與最穩健的轉正、Padding 方法。
    """
    # --- 1. 讀取影像 ---
    try:
        img_color = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        # 確保影像是三通道的，以防讀到灰階或帶有 Alpha 通道的影像
        if img_color.shape[2] == 4:
            img_color = cv2.cvtColor(img_color, cv2.COLOR_BGRA2BGR)
        
        img_gray = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY)
    except Exception as e:
        print(f"錯誤：無法讀取或處理影像 '{image_path}'. 詳細資訊: {e}")
        return None
    
    print(img_gray.shape)

    # --- 2. 形態學處理 (超級膨脹 -> 面積篩選) ---
    canny_edges = cv2.Canny(img_gray, 100, 250)
    dilate_kernel = np.ones((71, 71), np.uint8)
    canny_dilated = cv2.dilate(canny_edges, dilate_kernel)

    num_labels, labels_matrix, stats, _ = cv2.connectedComponentsWithStats(canny_dilated, connectivity=8)
    filtered_image = np.zeros_like(canny_dilated)
    min_area_threshold = 100000
    
    for i in range(1, num_labels):
        if stats[i, cv2.CC_STAT_AREA] >= min_area_threshold:
            filtered_image[labels_matrix == i] = 255

    # --- 3. 尋找並繪製最大輪廓 ---
    contours, _ = cv2.findContours(filtered_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    contour_image = cv2.cvtColor(filtered_image, cv2.COLOR_GRAY2BGR)
    if not contours:
        print(f"警告：在 '{image_path}' 中找不到輪廓。")
        max_contour = None
    else:
        max_contour = max(contours, key=cv2.contourArea)
        cv2.drawContours(contour_image, [max_contour], -1, (0, 255, 0), 5)

    # --- 4. 裁切邏輯 (假設這是你之前使用的裁切邏輯) ---
    final_crop = None
    if max_contour is not None:
        try:
            rect = cv2.minAreaRect(max_contour)
            (w_rect, h_rect), center, angle = rect[1], rect[0], rect[2]
            
            if w_rect < h_rect:
                angle += 90
                width, height = h_rect, w_rect
            else:
                width, height = w_rect, h_rect
            
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            (H, W) = img_color.shape[:2]
            abs_cos, abs_sin = abs(M[0, 0]), abs(M[0, 1])
            bound_w, bound_h = int(H * abs_sin + W * abs_cos), int(H * abs_cos + W * abs_sin)
            
            M[0, 2] += bound_w / 2 - center[0]
            M[1, 2] += bound_h / 2 - center[1]
            
            rotated_image = cv2.warpAffine(img_color, M, (bound_w, bound_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            
            x_center_rot, y_center_rot = bound_w / 2, bound_h / 2
            x1 = int(x_center_rot - width / 2 - padding_val)
            y1 = int(y_center_rot - height / 2 - padding_val)
            x2 = int(x_center_rot + width / 2 + padding_val)
            y2 = int(y_center_rot + height / 2 + padding_val)

            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(rotated_image.shape[1], x2), min(rotated_image.shape[0], y2)
            
            # 將裁切操作放入 try 區塊內
            final_crop = rotated_image[y1:y2, x1:x2]

        except Exception as e:
            print(f"裁切過程中發生錯誤: {e}") 
        
    return final_crop 

### 主處理流程 ###

print(f"正在處理來自 '{input_folder}' 的圖片...")

for filename in os.listdir(input_folder):
    if filename.lower().endswith(('.jpeg', '.jpg', '.png', '.bmp', '.tiff', '.webp')):
        full_image_path = os.path.join(input_folder, filename)
        print(f"  - 處理中：{filename}")
        cropped_result = process_image_and_crop(full_image_path, padding_val=2)

        if cropped_result is not None and cropped_result.size > 0:
            output_filename = f"cropped_{filename}"
            output_full_path = os.path.join(output_folder, output_filename)

            try:
                _, ext = os.path.splitext(output_full_path)
                is_success, im_buf_arr = cv2.imencode(ext, cropped_result)
                if is_success:
                    im_buf_arr.tofile(output_full_path)
                    print(f"    已儲存至：{output_full_path}")
                else:
                    print(f"    無法為 '{filename}' 編碼圖片。")
            except Exception as e:
                print(f"    儲存 '{output_full_path}' 時發生錯誤：{e}")
        else:
            print(f"    無法處理或找不到 '{filename}' 的主要輪廓。")

print(f"所有圖片處理完畢。結果已儲存至 '{output_folder}'。")