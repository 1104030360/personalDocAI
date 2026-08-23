"""無線鏡頭的 API 資料格式（Pydantic 模型，Phase 36）。

只有「建立配對」需要自己的回應模型：
快門那張照片的回應直接沿用 app/schemas/photo.py 的 UploadResponse
（同一套上傳流程、同一個形狀，桌面才接得上既有的三關彈窗鏈）。
"""

from pydantic import BaseModel


class CameraSessionOut(BaseModel):
    """POST /camera/session 的回應。

    三個欄位剛好對應桌面畫面上的三件事：
    - token：之後每一支 API 與 WebSocket 都要帶（10 分鐘有效，全在記憶體）
    - phone_url：手機要開的取景頁網址；掃不到 QR 時可以照著念
    - qr_svg：上面那個網址畫成的 QR（inline SVG 字串，前端直接塞進 <div>）
    """

    token: str
    phone_url: str
    qr_svg: str
