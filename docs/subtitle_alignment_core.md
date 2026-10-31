# 字幕對齊核心

`subtitle_alignment_core.py` 只使用 Python 標準函式庫，適用 Python 3.10+。
本交付不修改 GUI、notebook、Ollama、Helsinki 或雲端後端接線。

## 固定契約

呼叫：

```python
from subtitle_alignment_core import translate_cues, parse_model_response

cues = [
    {"id": "clip-a:moon", "source": "月亮郵差到了。",
     "start": "00:00:01,000", "end": "00:00:02,000"},
    {"id": "clip-a:tea", "source": "雲朵茶\n準備好了。",
     "start": "00:00:03,000", "end": "00:00:05,000"},
]

def fake_backend(request):
    # 真實 adapter 應要求模型保留不透明 id；不可把模型序號當成 id。
    # request 僅含 cues(id/source)、source_language、target_language。
    translations = {"clip-a:moon": "The moon courier arrived.",
                    "clip-a:tea": "Cloud tea is ready."}
    return {"items": [{"id": c["id"], "text": translations[c["id"]]}
                      for c in reversed(request["cues"])],
            "failures": [], "diagnostics": []}

# 分批與整份使用同一入口。id 在所有批次間也宜保持唯一。
output, failures = [], []
for offset in range(0, len(cues), 2):
    result = translate_cues(
        cues[offset:offset + 2], fake_backend,
        source_language="zh", target_language="en",
        bilingual=True, max_retries=2,
    )
    output.extend(result["cues"])
    failures.extend(result["failures"])

# 失敗摘要只需 id/code，不要列印後端原始回應或憑證。
for failure in failures:
    print(failure["id"], failure["code"])
```

回傳 `{"cues": [...], "failures": [...]}`。每個 cue 保留輸入 id、source、
start、end 與順序，新增 text 與 status (`ok` / `failed`)。
成功雙語 text 為 `source + "\n" + translation`；英文模式僅輸出譯文。
失敗一律為 `source + "\n[TRANSLATION_FAILED]"`，不會靜默留白。
空輸入不呼叫後端。多行 source 原樣傳遞，換行不表示另一個 cue。
呼叫者須提供唯一字串 id、字串 source/start/end；重複 id 或不合法參數
會在呼叫後端前拋出 ValueError。

Backend 回應必須恰含 `items`、`failures`、`diagnostics` 三欄。
items 為 `[{"id": str, "text": str}]`，failures 為 `[{"id": str, "code": str}]`，
diagnostics 為字串列表；每個請求 id 必須恰好出現一次，兩列表不能重疊。
合法 code：`invalid_response`、`retry_exhausted`、`missing_key`、`backend_error`。
核心不輸出、儲存或轉傳後端 diagnostics／例外內容；後端仍須自行確保不記錄憑證。

## 嚴格模型 JSON

Adapter 可用 `parse_model_response(raw_text, expected_ids)` 將模型文字轉為
backend 契約。只接受完整的 `{"items": [{"id": str, "text": str}]}` JSON，
拒絕解說、Markdown fence、思考區塊、截斷、重複 JSON key、空白譯文、
缺漏／重複／未知 id、額外欄位與錯誤結構。
不採用位置配對；倒序回應可透過 id 安全還原。

任何結構或識別歧義都使該次回應整體失效，避免保留可能已合併鄰句的譯文。
合法 backend 回應若明確提供成功 items 及失敗 failures，則保留成功結果，
之後只傳未完成項目。已成功的譯文不會被後續重試覆蓋。

可觀測的合併（缺 id）、拆分（重複或未知 id）、重新編號都會拒絕。
若模型保留所有合法 id，卻在 text 內合併句意、交換譯文或加入解說，
單靠此契約無法辨識；本核心不宣稱能偵測任意語義錯譯。

## 所有重試上限

`max_retries` 預設 2，必須是非負整數（不接受 bool）。

1. 批次階段最多 `1 + max_retries` 次，每次只重送尚未成功的項目。
2. 原始輸入超過一個 cue 時，批次階段結束後，每個未完成 cue 再逐條
   呼叫最多 `1 + max_retries` 次。逐條回應同樣嚴格驗證。
3. 原始輸入只有一個 cue 時，批次階段已是逐條，不再重複第二階段。

n > 1 時，核心總 backend 呼叫最多 `(n + 1) * (max_retries + 1)` 次；
n = 1 時最多 `max_retries + 1` 次；n = 0 時為 0 次。
每個獨立批次都有自己的上限。內容修復不 sleep；HTTP/429 的等待及重試
屬後端責任，各次核心呼叫仍須受後端自身上限約束。

耗盡時 failures 保留最後一次失敗原因：不合法回應為 invalid_response，
後端例外為 backend_error，合法 backend failures 保留其 code（含
retry_exhausted 或 missing_key）。耗盡不會產生空白或挪用其他句譯文。
核心可處理後端拋出的 Exception，但無法限制後端本身永不返回的呼叫；
網路 adapter 應自行設定 timeout。

## 離線測試

```bash
python3 -m venv .venv
.venv/bin/python -m unittest discover -s tests -v
```

所有測試字幕皆虛構；核心測試不需第三方套件、GPU、網路或 API key。
