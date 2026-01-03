export default {
  async fetch(request, env) {
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    // --- DEBUG 區塊開始 ---
    // 檢查環境變數是否存在
    if (!env.DATASET_BUCKET) {
      return new Response(JSON.stringify({
        error: "CRITICAL ERROR: env.DATASET_BUCKET is undefined! Binding failed."
      }), {
        status: 500,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }
    // --- DEBUG 區塊結束 ---

    try {
      const formData = await request.formData();
      const imageFile = formData.get("image");
      const labelText = formData.get("label");
      const originalName = formData.get("filename");

      if (!imageFile || !labelText) {
        return new Response(JSON.stringify({ error: "Missing image or label" }), { 
          status: 400,
          headers: corsHeaders 
        });
      }

      const timestamp = Date.now();
      const random = Math.floor(Math.random() * 10000);
      const safeName = (originalName || "unknown").replace(/\.[^/.]+$/, "").replace(/[^a-zA-Z0-9-_]/g, "_");
      const uniqueId = `${timestamp}_${random}_${safeName}`;

      // 4. 存入 R2 (路徑包含你的 yolo-dataset 資料夾)
      await env.DATASET_BUCKET.put(
        `yolo-dataset/images/${uniqueId}.jpg`, 
        imageFile, 
        { httpMetadata: { contentType: imageFile.type } }
      );

      await env.DATASET_BUCKET.put(
        `yolo-dataset/labels/${uniqueId}.txt`, 
        labelText, 
        { httpMetadata: { contentType: "text/plain" } }
      );

      return new Response(JSON.stringify({ success: true, id: uniqueId }), {
        headers: {
          "Content-Type": "application/json",
          ...corsHeaders,
        },
      });

    } catch (e) {
      return new Response(JSON.stringify({ 
        error: e.message, 
        stack: e.stack 
      }), {
        status: 500,
        headers: { 
          ...corsHeaders,
          "Content-Type": "application/json"
        },
      });
    }
  },
};