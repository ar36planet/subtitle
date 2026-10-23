# 語音辨識字幕工具

本地語音辨識 + 字幕翻譯工具，專為 Apple Silicon Mac 設計。

## 功能

- **語音辨識**：使用 mlx-whisper，吃 Apple Metal GPU 加速
- **字幕翻譯**：支援 Helsinki 翻譯模型與 Ollama 本地 LLM
- 支援音訊（mp3、wav、m4a、flac、aac、ogg）和影片（mp4、mov、avi、mkv、webm、m4v）
- 輸出 `.srt` 字幕檔或 `.txt` 逐字稿
- 翻譯結果可逐行編輯後再匯出

## 環境需求

- Apple Silicon Mac（M1 以上）
- Python 3.10+
- ffmpeg
- Ollama（使用 LLM 翻譯時需要）

## 安裝

**1. 安裝系統依賴**

```bash
brew install ffmpeg
brew install ollama
```

**2. 建立 Python 虛擬環境並安裝套件**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**3. 下載 Ollama 模型（擇一即可）**

```bash
ollama pull gemma4:e4b       # 推薦，翻譯口語字幕效果好
ollama pull qwen2.5:7b       # 備選
```

## 使用方式

```bash
source .venv/bin/activate
python3 transcriber.py
```

### 語音辨識

1. 選擇音訊或影片檔案
2. 選擇輸出目錄
3. 設定語言與模型（預設 large-v3，首次使用會自動下載約 1.5GB）
4. 按「開始辨識」

> 提示語欄位建議留空，填入指令式提示會導致辨識內容錯誤。

### 字幕翻譯

1. 切換到「字幕翻譯」分頁
2. 匯入調整好的 `.srt` 檔
3. 選擇翻譯模型（預設 gemma4，整批送入保留前後文語意）
4. 按「翻譯全部」，完成後可直接在欄位裡修改
5. 確認後按「匯出 SRT」

## 在 Colab 上執行

沒有 Apple Silicon Mac 也可以用 Google Colab 的免費 GPU 做語音辨識（faster-whisper）：

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ar36planet/subtitle/blob/main/colab_transcribe.ipynb)

1. 「執行階段 → 變更執行階段類型」選 **T4 GPU**
2. 依序執行三個區塊：安裝套件 → 掛載雲端硬碟（選用）→ 語音辨識
3. 「來源」留空會跳出上傳視窗；也可填檔案路徑、資料夾、`.txt` 清單或 YouTube 網址

> 請在本機修改 notebook 後 commit，Colab 只用來執行。若要從 Colab 存回 GitHub，記得取消勾選「包含儲存格輸出」。

## 模型說明

### 語音辨識模型

| 模型 | 說明 |
|------|------|
| large-v3 | 最準確，推薦 |
| turbo | 速度與準確度平衡 |
| medium / small / base | 速度依序提升，準確度依序下降 |

### 翻譯模型

| 模型 | 類型 | 說明 |
|------|------|------|
| Helsinki | 輕量翻譯模型 | 速度快，口語表現較弱 |
| gemma4 | Ollama LLM | 口語化字幕表現佳，推薦 |
| qwen2.5:7b | Ollama LLM | 中英翻譯備選 |

## 新增 Ollama 模型

在 `transcriber.py` 的 `TRANS_MODELS` 加入：

```python
'中→英 (你的模型)': {'type': 'ollama', 'model': '模型名稱'},
```

接著執行 `ollama pull 模型名稱` 即可。
