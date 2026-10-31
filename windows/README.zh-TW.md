# Windows + 傳統 ESP32（藍牙滑鼠）版

這個分支以 [ESP32 iPhone Agent](https://github.com/onehumanbeing/esp32-iphone-agent)（Henry Yuan，MIT）的 `legacy` 版為基礎，改成：

- **板子**：傳統 ESP32（ESP-WROOM-32 + CP2102 之類的開發板），以藍牙滑鼠／鍵盤配對 iPhone，不插手機。
- **板子 ↔ 電腦**：USB 序列線（韌體用 `SERIAL_LINK=1` 編譯），不需要 Wi-Fi 密碼。
- **眼睛**：Windows 上的 UxPlay 接收 iPhone 螢幕鏡像（`uxplay-win64` 免安裝包）。
- **大腦**：電腦上的 Python server 與網頁介面，呼叫任何 OpenAI 相容的視覺模型。

## 需要

- Windows 10/11、Python 3.10 以上
- 傳統 ESP32 開發板，Windows 已裝好 CP210x（或 CH340）驅動
- iPhone 與電腦在同一個 Wi-Fi（不能開 AP 隔離）
- 視覺模型的 API key

## 步驟

1. **燒錄**：到 Actions 的「Windows classic BLE」下載 `firmware-classic-ble`，用 https://espressif.github.io/esptool-js/ 把 `hid_bridge_ble_c3.ino.merged.bin` 燒在 `0x0`。
2. **放 UxPlay**：下載 `uxplay-win64`，解壓縮後把 `uxplay-win64` 資料夾放在專案根目錄（和 `server`、`windows` 同層）。
3. **安裝**：雙擊 `windows\setup.bat`，再用記事本打開 `server\.env` 填 `LLM_API_KEY`（和 `LLM_BASE_URL`、`LLM_MODEL`）。
4. **啟動**：雙擊 `windows\start.bat`。第一次 Windows 防火牆會詢問 uxplay.exe，勾「私人網路」並允許。
5. **iPhone**：
   - 設定 → 藍牙 → 點 **iPhone Agent HID** 配對
   - 設定 → 輔助使用 → 觸控 → 開啟 **AssistiveTouch**（會出現游標）
   - 控制中心 → 螢幕鏡像輸出 → **iPhone Agent**
6. **校準**：網頁介面 → Manual controls → **Calibrate**。之後就能輸入任務。

## 已知限制

- 只能輸入 ASCII，中文要另外處理。
- 手機鎖定時藍牙和鏡像都會斷，用的時候讓螢幕保持開著。
- 藍牙回報間隔不如 USB 平均，點擊偏差大時調 AssistiveTouch 的「追蹤速度」後重新校準，之後別再改。

公開展示或發文時請註明原專案：Based on ESP32 iPhone Agent by Henry Yuan。
