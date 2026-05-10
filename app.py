import streamlit as st
import requests
import re
import html
import time
from concurrent.futures import ThreadPoolExecutor
try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except Exception:
    from api_keys import OPENAI_API_KEY, GEMINI_API_KEY

# ============================================================
# ChatGPT x Gemini 討論アプリ C版（A表示整形：HTML改行対応）
# - app.pyからStreamlitを起動しない
# - APIキーはクラウドでは st.secrets、ローカルでは api_keys.py から読み込む
# - ChatGPT/Gemini初回回答は並列実行
# - 通常時：ChatGPT要点 → Gemini要点 → 一致点と相違点 → ChatGPT詳細 → Gemini詳細
# - 要点/差分はMarkdownではなくHTMLで①②③を強制縦並び表示
# ============================================================

st.set_page_config(page_title="ChatGPT x Gemini 討論", page_icon="💬", layout="centered")

OPENAI_MODELS = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.3",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5.0",
    "gpt-4.1",
    "gpt-4.1-mini",
]

GEMINI_MODELS = [
    "gemini-flash-latest",
    "gemini-3-flash-preview",
    "gemini-2.5-pro-latest",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
]

OPENAI_BILLING_URL = "https://platform.openai.com/account/billing"

ANSWER_INSTRUCTION = """
必ず日本語で、以下の形式で回答してください。

【要点】
① 結論（理由）
② 結論（理由）
③ 結論（理由）

【詳細】

## ① 結論（理由）
詳細説明

## ② 結論（理由）
詳細説明

## ③ 結論（理由）
詳細説明

厳守ルール：
1. 【要点】は3〜5点にしてください。
2. 【要点】は必ず「①②③④⑤」の形式にしてください。
3. 各要点は必ず「結論＋根拠（〜ため）」の1行で書いてください。
4. ①②③④⑤はそれぞれ改行してください。
5. 各要点の中では改行しないでください。
6. 抽象度を揃えてください。
7. 【詳細】の各見出しも必ず「## ① ...」「## ② ...」の形式にしてください。
8. 【詳細】の各見出し文言は、対応する【要点】の文言を一字一句そのまま引用してください。
9. 例：【要点】が「① 成長余地がある（市場拡大が続くため）」なら、【詳細】見出しは必ず「## ① 成長余地がある（市場拡大が続くため）」にしてください。
10. 【詳細】本文は箇条書きを強制しません。自然文で読みやすく説明してください。
11. 必要な場合のみ箇条書きを使ってください。
12. 不確かなことは推測せず、「現時点では不明」と明記してください。
13. 事実と仮説を区別してください。
14. 出力前に、【要点】の①②③と【詳細】見出しの①②③が一字一句一致しているか確認してください。
"""

DIFF_INSTRUCTION = """
以下のChatGPT要点とGemini要点を比較し、日本語で、純粋に違いがわかるように簡潔に整理してください。

【差分】

一致：
① 結論（共通の理由）
② 結論（共通の理由）

相違：
① 結論（ズレた理由）
② 結論（ズレた理由）

厳守ルール：
1. 「一致」と「相違」だけで整理してください。
2. 各項目は必ず「結論＋理由（〜ため）」の1行で書いてください。
3. ①②③④⑤はそれぞれ改行してください。
4. 各項目の中では改行しないでください。
5. 「一致」はなぜ一致しているかを明示してください。
6. 「相違」は何がズレているか＋なぜズレたかを明示してください。
7. 抽象度を揃えてください。
8. 長い説明は禁止です。
9. 不明点は「現時点では不明」と書いてください。
"""

CROSS_COMMENT_INSTRUCTION = """
以下の相手の回答に対して、日本語で見解を示してください。

【要点】
① 見解（理由）
② 見解（理由）
③ 見解（理由）

【詳細】

## ① 見解（理由）
詳細説明

## ② 見解（理由）
詳細説明

## ③ 見解（理由）
詳細説明

厳守ルール：
1. 相手の回答を具体的に参照してください。
2. 賛成点・違和感・補足すべき点を明確にしてください。
3. 必要以上に長くしないでください。
4. 【要点】と【詳細】は①②③形式にしてください。
5. ①②③はそれぞれ改行してください。
6. 各要点の中では改行しないでください。
7. 詳細本文は自然文で構いません。
8. 【詳細】の各見出し文言は、対応する【要点】の文言を一字一句そのまま引用してください。
"""

st.markdown(
    """
<style>
.block-container {
    max-width: 900px;
    padding-top: 1rem;
    padding-bottom: 5.5rem;
}
.user-box {
    background: #eef2ff;
    border: 1px solid #e0e7ff;
    padding: 0.85rem 1rem;
    border-radius: 1rem;
    margin: 0.8rem 0;
}
.answer-card {
    border: 1px solid #e5e7eb;
    background: #ffffff;
    padding: 0.95rem 1rem;
    border-radius: 1rem;
    margin: 0.75rem 0 1rem 0;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
}
.answer-card.chatgpt { border-left: 4px solid #10a37f; }
.answer-card.gemini { border-left: 4px solid #4285f4; }
.answer-card.diff {
    border-left: 4px solid #f59e0b;
    background: #fffbeb;
}
.answer-card.cross {
    border-left: 4px solid #8b5cf6;
    background: #faf5ff;
}
.answer-title {
    font-size: 1rem;
    font-weight: 700;
    margin-bottom: 0.2rem;
}
.answer-model {
    font-size: 0.72rem;
    color: #6b7280;
    margin-bottom: 0.6rem;
}
.numbered-block { margin-top: 0.2rem; }
.numbered-row {
    display: flex;
    gap: 0.45rem;
    line-height: 1.65;
    margin: 0.2rem 0;
}
.numbered-mark {
    flex: 0 0 auto;
    font-weight: 700;
}
.numbered-text { flex: 1 1 auto; }
.diff-section-label {
    font-weight: 700;
    margin-top: 0.55rem;
    margin-bottom: 0.2rem;
}
div[data-testid="stMarkdownContainer"] h2 {
    font-size: 1rem !important;
    font-weight: 700 !important;
    line-height: 1.45 !important;
    margin-top: 0.9rem !important;
    margin-bottom: 0.35rem !important;
}
div[data-testid="stMarkdownContainer"] p { line-height: 1.7 !important; }
div[data-testid="stMarkdownContainer"] li {
    margin: 0.2rem 0 !important;
    line-height: 1.65 !important;
}
section[data-testid="stSidebar"] div.stButton > button {
    width: 100% !important;
    border-radius: 0.7rem !important;
}

/* AI選択radioをボタン風にする */
div[role="radiogroup"] > label {
    border: 1px solid #e5e7eb;
    padding: 0.35rem 0.75rem;
    border-radius: 999px;
    margin-right: 6px;
    cursor: pointer;
}
div[role="radiogroup"] > label:hover { background-color: #f3f4f6; }

/* PCだけ入力欄を固定フッター風にする */
@media (min-width: 768px) {
    div[data-testid="stChatInput"] {
        position: fixed;
        bottom: 1rem;
        left: 50%;
        transform: translateX(-50%);
        width: min(860px, calc(100vw - 2rem));
        z-index: 999;
        background: white;
        border-radius: 1rem;
        box-shadow: 0 4px 18px rgba(0,0,0,0.08);
    }
}

/* スマホでは固定しない */
@media (max-width: 767px) {
    .block-container { padding-bottom: 2rem; }
    div[data-testid="stChatInput"] {
        position: static !important;
        transform: none !important;
        width: 100% !important;
        box-shadow: none !important;
    }
}

/* フェード風表示 */
@keyframes fadeSlideIn {
    from {
        opacity: 0;
        transform: translateY(8px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}
.answer-card {
    animation: fadeSlideIn 0.28s ease-out;
}
.user-box {
    animation: fadeSlideIn 0.22s ease-out;
}


/* UI階層・余白調整 */
.answer-card {
    padding: 1.05rem 1.1rem;
    margin: 0.9rem 0 1.15rem 0;
}
.answer-card.chatgpt,
.answer-card.gemini {
    background: #ffffff;
}
.answer-card.diff {
    background: #fff7ed;
    border-color: #fed7aa;
}
.answer-card.cross {
    background: #faf5ff;
    border-color: #ddd6fe;
}
.answer-title {
    letter-spacing: 0.01em;
}
.answer-card.chatgpt .answer-title,
.answer-card.gemini .answer-title {
    color: #111827;
}
.answer-card.diff .answer-title {
    color: #9a3412;
}

/* 要点カードを少し強調 */
.answer-card.chatgpt:has(.numbered-block),
.answer-card.gemini:has(.numbered-block) {
    background: linear-gradient(180deg, #ffffff 0%, #f9fafb 100%);
}
.numbered-row {
    padding: 0.18rem 0;
}
.numbered-mark {
    min-width: 1.4rem;
    color: #111827;
}
.numbered-text {
    font-weight: 500;
}

/* 詳細カードは少し控えめ */
.answer-card:has(h2) {
    background: #ffffff;
}
.answer-card:has(h2) .answer-title {
    color: #374151;
}
.answer-card:has(h2) .answer-model {
    color: #9ca3af;
}

/* ローディング風カード */
.loading-card {
    border: 1px solid #fed7aa;
    border-left: 4px solid #f59e0b;
    background: #fffbeb;
    padding: 1rem 1.1rem;
    border-radius: 1rem;
    margin: 0.9rem 0 1.15rem 0;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    animation: fadeSlideIn 0.28s ease-out;
}
.loading-title {
    font-size: 1rem;
    font-weight: 700;
    color: #9a3412;
    margin-bottom: 0.35rem;
}
.loading-dots::after {
    content: "";
    animation: dots 1.2s steps(4, end) infinite;
}
@keyframes dots {
    0% { content: ""; }
    25% { content: "."; }
    50% { content: ".."; }
    75% { content: "..."; }
    100% { content: ""; }
}

/* サイドバー復帰ボタンを控えめにする */
div[data-testid="stButton"] > button {
    border-radius: 999px;
}


/* ===== Dark Mode Fix ===== */
@media (prefers-color-scheme: dark) {

    body {
        background-color: #000000;
        color: #f9fafb;
    }

    .answer-card {
        background: #111827;
        border-color: #374151;
    }

    .answer-title {
        color: #f9fafb;
    }

    .answer-model {
        color: #9ca3af;
    }

    .numbered-mark {
        color: #f9fafb;
    }

    .numbered-text {
        color: #e5e7eb;
    }

    .user-box {
        background: #1f2937;
        border-color: #374151;
        color: #f9fafb;
    }

    textarea, input {
        color: #f9fafb !important;
        background-color: #111827 !important;
    }
}


/* ===== Dark Mode Additional Visibility Fix ===== */
@media (prefers-color-scheme: dark) {

    /* ユーザー入力欄 */
    textarea,
    textarea::placeholder,
    input,
    input::placeholder,
    [data-testid="stChatInput"] textarea {
        color: #f9fafb !important;
        background-color: #111827 !important;
        caret-color: #f9fafb !important;
        opacity: 1 !important;
    }

    /* ユーザー質問カード */
    .user-box,
    .user-box * {
        color: #f9fafb !important;
    }

    /* 箇条書き番号 */
    .numbered-mark {
        color: #f9fafb !important;
        font-weight: 700 !important;
    }

    /* 箇条書き本文 */
    .numbered-text {
        color: #f3f4f6 !important;
    }

    /* 見出し */
    h1, h2, h3, h4 {
        color: #f9fafb !important;
    }
}


/* ===== Light Mode Visibility Fix ===== */
@media (prefers-color-scheme: light) {

    .numbered-mark {
        color: #111827 !important;
        font-weight: 700 !important;
    }

    .numbered-text {
        color: #111827 !important;
    }

    .user-box,
    .user-box * {
        color: #111827 !important;
    }

    textarea,
    textarea::placeholder,
    input,
    input::placeholder,
    [data-testid="stChatInput"] textarea {
        color: #111827 !important;
        background-color: #ffffff !important;
        caret-color: #111827 !important;
    }
}


/* ===== Sidebar Toggle Button ===== */
.sidebar-restore-wrapper {
    position: fixed;
    top: 0.75rem;
    left: 0.75rem;
    z-index: 99999;
}
.sidebar-restore-wrapper button {
    border-radius: 999px !important;
    padding: 0.25rem 0.65rem !important;
    min-height: 2rem !important;
}
@media (prefers-color-scheme: dark) {
    .sidebar-restore-wrapper button {
        background: #111827 !important;
        color: #f9fafb !important;
        border: 1px solid #374151 !important;
    }
}
@media (prefers-color-scheme: light) {
    .sidebar-restore-wrapper button {
        background: #ffffff !important;
        color: #111827 !important;
        border: 1px solid #d1d5db !important;
    }
}


/* ===== Final Dark Mode Override ===== */
@media (prefers-color-scheme: dark) {

    html, body, .stApp, [data-testid="stAppViewContainer"] {
        background-color: #000000 !important;
        color: #f9fafb !important;
    }

    .block-container {
        background-color: #000000 !important;
        color: #f9fafb !important;
    }

    .answer-card,
    .answer-card.chatgpt,
    .answer-card.gemini,
    .answer-card.diff,
    .answer-card.cross,
    .answer-card:has(h2),
    .answer-card.chatgpt:has(.numbered-block),
    .answer-card.gemini:has(.numbered-block) {
        background: #111827 !important;
        border-color: #374151 !important;
        color: #f9fafb !important;
        box-shadow: 0 1px 2px rgba(255,255,255,0.04) !important;
    }

    .answer-card.chatgpt {
        border-left-color: #34d399 !important;
    }

    .answer-card.gemini {
        border-left-color: #60a5fa !important;
    }

    .answer-card.diff {
        border-left-color: #fbbf24 !important;
    }

    .answer-card.cross {
        border-left-color: #a78bfa !important;
    }

    .answer-title,
    .answer-card.chatgpt .answer-title,
    .answer-card.gemini .answer-title,
    .answer-card.diff .answer-title,
    .answer-card.cross .answer-title,
    .answer-card:has(h2) .answer-title {
        color: #f9fafb !important;
    }

    .answer-model,
    .answer-card:has(h2) .answer-model {
        color: #d1d5db !important;
    }

    .numbered-mark,
    .numbered-row .numbered-mark {
        color: #ffffff !important;
        font-weight: 800 !important;
    }

    .numbered-text,
    .numbered-row .numbered-text {
        color: #f3f4f6 !important;
        font-weight: 500 !important;
    }

    .diff-section-label {
        color: #fbbf24 !important;
    }

    .user-box,
    .user-box * {
        background: #1f2937 !important;
        border-color: #374151 !important;
        color: #f9fafb !important;
    }

    div[data-testid="stMarkdownContainer"],
    div[data-testid="stMarkdownContainer"] *,
    p, span, li, h1, h2, h3, h4, h5, h6 {
        color: #f9fafb !important;
    }

    textarea,
    textarea::placeholder,
    input,
    input::placeholder,
    [data-testid="stChatInput"] textarea,
    [data-testid="stChatInput"] textarea::placeholder,
    [data-testid="stTextArea"] textarea,
    [data-testid="stTextInput"] input {
        color: #f9fafb !important;
        background-color: #111827 !important;
        caret-color: #f9fafb !important;
        opacity: 1 !important;
        -webkit-text-fill-color: #f9fafb !important;
    }

    [data-testid="stChatInput"],
    [data-testid="stChatInput"] > div,
    [data-testid="stChatInput"] div {
        background-color: #111827 !important;
        color: #f9fafb !important;
    }

    section[data-testid="stSidebar"],
    section[data-testid="stSidebar"] * {
        background-color: #111827 !important;
        color: #f9fafb !important;
    }

    div[role="radiogroup"] > label {
        background-color: #111827 !important;
        border-color: #374151 !important;
        color: #f9fafb !important;
    }

    div[role="radiogroup"] > label:hover {
        background-color: #1f2937 !important;
    }

    button,
    div[data-testid="stButton"] > button {
        background-color: #111827 !important;
        color: #f9fafb !important;
        border-color: #374151 !important;
    }
}


/* ===== Chat Input Background Tuning ===== */

/* Light mode */
@media (prefers-color-scheme: light) {
    div[data-testid="stChatInput"] {
        background: #f3f4f6 !important;
    }

    div[data-testid="stChatInput"] textarea,
    [data-testid="stChatInput"] textarea {
        background: #f3f4f6 !important;
        color: #111827 !important;
    }
}

/* Dark mode */
@media (prefers-color-scheme: dark) {
    div[data-testid="stChatInput"] {
        background: #111827 !important;
    }

    div[data-testid="stChatInput"] textarea,
    [data-testid="stChatInput"] textarea {
        background: #111827 !important;
        color: #f9fafb !important;
    }
}


/* ===== Final Chat Input Force Background ===== */

/* Light */
@media (prefers-color-scheme: light) {

    div[data-testid="stChatInput"] {
        background: #f3f4f6 !important;
        border: 1px solid #d1d5db !important;
    }

    div[data-testid="stChatInput"] > div {
        background: #f3f4f6 !important;
    }

    div[data-testid="stChatInput"] textarea,
    div[data-testid="stChatInput"] textarea:focus,
    div[data-testid="stChatInput"] textarea:active,
    [data-testid="stChatInput"] textarea {
        background-color: #f3f4f6 !important;
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        box-shadow: none !important;
    }
}

/* Dark */
@media (prefers-color-scheme: dark) {

    div[data-testid="stChatInput"] {
        background: #111827 !important;
        border: 1px solid #374151 !important;
    }

    div[data-testid="stChatInput"] > div {
        background: #111827 !important;
    }

    div[data-testid="stChatInput"] textarea,
    div[data-testid="stChatInput"] textarea:focus,
    div[data-testid="stChatInput"] textarea:active,
    [data-testid="stChatInput"] textarea {
        background-color: #111827 !important;
        color: #f9fafb !important;
        -webkit-text-fill-color: #f9fafb !important;
        box-shadow: none !important;
    }
}


/* ===== Native Sidebar Toggle Visibility ===== */
div[data-testid="collapsedControl"] {
    display: block !important;
    visibility: visible !important;
    opacity: 1 !important;
    z-index: 99999 !important;
}


/* ===== Final Chat Input Empty Placeholder Background Fix ===== */

/* Light mode: input container and empty placeholder state */
@media (prefers-color-scheme: light) {
    div[data-testid="stChatInput"],
    div[data-testid="stChatInput"] *,
    div[data-testid="stChatInput"] > div,
    div[data-testid="stChatInput"] > div > div,
    div[data-testid="stChatInput"] section,
    div[data-testid="stChatInput"] form {
        background-color: #f3f4f6 !important;
    }

    div[data-testid="stChatInput"] textarea,
    div[data-testid="stChatInput"] textarea::placeholder,
    div[data-testid="stChatInput"] [contenteditable="true"],
    div[data-testid="stChatInput"] [contenteditable="true"]::placeholder {
        background-color: #f3f4f6 !important;
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        opacity: 1 !important;
    }

    div[data-testid="stChatInput"] {
        border: 1px solid #d1d5db !important;
        box-shadow: 0 4px 18px rgba(0,0,0,0.06) !important;
    }
}

/* Dark mode: input container and empty placeholder state */
@media (prefers-color-scheme: dark) {
    div[data-testid="stChatInput"],
    div[data-testid="stChatInput"] *,
    div[data-testid="stChatInput"] > div,
    div[data-testid="stChatInput"] > div > div,
    div[data-testid="stChatInput"] section,
    div[data-testid="stChatInput"] form {
        background-color: #111827 !important;
    }

    div[data-testid="stChatInput"] textarea,
    div[data-testid="stChatInput"] textarea::placeholder,
    div[data-testid="stChatInput"] [contenteditable="true"],
    div[data-testid="stChatInput"] [contenteditable="true"]::placeholder {
        background-color: #111827 !important;
        color: #f9fafb !important;
        -webkit-text-fill-color: #f9fafb !important;
        opacity: 1 !important;
    }

    div[data-testid="stChatInput"] {
        border: 1px solid #374151 !important;
        box-shadow: 0 4px 18px rgba(255,255,255,0.04) !important;
    }
}


/* ===== Final Sidebar Edge Toggle + Chat Input Fix ===== */
@media (prefers-color-scheme: light) {
    .sidebar-edge-toggle button {
        background: #ffffff !important;
        color: #111827 !important;
        border: 1px solid #d1d5db !important;
        box-shadow: 0 2px 10px rgba(0,0,0,0.10) !important;
    }

    div[data-testid="stChatInput"],
    div[data-testid="stChatInput"] *,
    div[data-testid="stChatInput"] textarea,
    div[data-testid="stChatInput"] textarea::placeholder {
        background-color: #f3f4f6 !important;
        color: #111827 !important;
        -webkit-text-fill-color: #111827 !important;
        opacity: 1 !important;
    }
}

@media (prefers-color-scheme: dark) {
    .sidebar-edge-toggle button {
        background: #111827 !important;
        color: #f9fafb !important;
        border: 1px solid #374151 !important;
        box-shadow: 0 2px 10px rgba(255,255,255,0.08) !important;
    }

    div[data-testid="stChatInput"],
    div[data-testid="stChatInput"] *,
    div[data-testid="stChatInput"] textarea,
    div[data-testid="stChatInput"] textarea::placeholder {
        background-color: #111827 !important;
        color: #f9fafb !important;
        -webkit-text-fill-color: #f9fafb !important;
        opacity: 1 !important;
    }
}


/* ===== Sidebar Auto-Hide Disabled ===== */
/* Native Streamlit sidebar behavior is used. Do not force sidebar position. */
.sidebar-edge-toggle {
    display: none !important;
}

/* ===== Cross Card Headings + iPhone Sidebar Fix ===== */
.answer-subtitle {
    font-size: 1rem;
    font-weight: 700;
    margin-top: 0.7rem;
    margin-bottom: 0.35rem;
    line-height: 1.45;
    color: #111827;
}

/* iPhoneでサイドバーを閉じたとき、左端に文字が残るのを防ぐ。
   Streamlit標準の開閉挙動を優先し、本文側からCSSで位置を強制しない。 */
@media (max-width: 767px) {
    section[data-testid="stSidebar"] {
        overflow: hidden !important;
    }

    section[data-testid="stSidebar"] * {
        max-width: 100% !important;
    }
}

@media (prefers-color-scheme: dark) {
    .answer-subtitle {
        color: #f9fafb !important;
    }
}

@media (prefers-color-scheme: light) {
    .answer-subtitle {
        color: #111827 !important;
    }
}

</style>
""",
    unsafe_allow_html=True,
)

if "turns" not in st.session_state:
    st.session_state.turns = []

if "sidebar_hidden" not in st.session_state:
    st.session_state.sidebar_hidden = False

if "execution_mode" not in st.session_state:
    st.session_state.execution_mode = "Multi"

if "multi_mode" not in st.session_state:
    st.session_state.multi_mode = "独立回答"

if "single_ai" not in st.session_state:
    st.session_state.single_ai = "ChatGPT"

# サイドバーは自動で隠さない。
# PC/iPhoneともにStreamlit標準のサイドバー表示に任せる。
# 理由：CSSで強制的に隠すと、PCでは復帰ボタンが出ない／iPhoneでは左端に崩れるため。

def split_numbered_items(text: str):
    if not text:
        return []

    normalized = text.strip()
    normalized = re.sub(r"【[^】]+】", "", normalized).strip()
    pattern = r"([①②③④⑤⑥⑦⑧⑨⑩])\s*(.*?)(?=\s*[①②③④⑤⑥⑦⑧⑨⑩]\s*|$)"

    items = []
    for mark, body in re.findall(pattern, normalized, flags=re.DOTALL):
        clean_body = " ".join(body.split())
        if clean_body:
            items.append((mark, clean_body))
    return items


def render_numbered_block(text: str):
    items = split_numbered_items(text)

    if not items:
        st.markdown(text)
        return

    html_parts = ['<div class="numbered-block">']
    for mark, body in items:
        html_parts.append(
            f'<div class="numbered-row">'
            f'<div class="numbered-mark">{html.escape(mark)}</div>'
            f'<div class="numbered-text">{html.escape(body)}</div>'
            f'</div>'
        )
    html_parts.append("</div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_diff_block(text: str):
    if not text:
        return

    working = text.strip()
    working = re.sub(r"【差分】", "", working).strip()

    match_same = re.search(r"一致：(.+?)(?=相違：|$)", working, flags=re.DOTALL)
    match_diff = re.search(r"相違：(.+)$", working, flags=re.DOTALL)

    if not match_same and not match_diff:
        render_numbered_block(text)
        return

    html_parts = []

    if match_same:
        html_parts.append('<div class="diff-section-label">一致：</div>')
        html_parts.append('<div class="numbered-block">')
        for mark, body in split_numbered_items(match_same.group(1)):
            html_parts.append(
                f'<div class="numbered-row">'
                f'<div class="numbered-mark">{html.escape(mark)}</div>'
                f'<div class="numbered-text">{html.escape(body)}</div>'
                f'</div>'
            )
        html_parts.append("</div>")

    if match_diff:
        html_parts.append('<div class="diff-section-label">相違：</div>')
        html_parts.append('<div class="numbered-block">')
        for mark, body in split_numbered_items(match_diff.group(1)):
            html_parts.append(
                f'<div class="numbered-row">'
                f'<div class="numbered-mark">{html.escape(mark)}</div>'
                f'<div class="numbered-text">{html.escape(body)}</div>'
                f'</div>'
            )
        html_parts.append("</div>")

    st.markdown("".join(html_parts), unsafe_allow_html=True)


def extract_summary(text: str) -> str:
    if not text:
        return ""
    if "【詳細】" in text:
        return text.split("【詳細】")[0].strip()
    return text.strip()


def extract_detail(text: str) -> str:
    if not text:
        return ""
    if "【詳細】" in text:
        # カード見出しが「ChatGPT 詳細」「Gemini 詳細」なので、本文側の【詳細】ラベルは表示しない。
        return text.split("【詳細】", 1)[1].strip()
    return text.strip()

def align_detail_headings_to_summary(text: str) -> str:
    if not text or "【要点】" not in text or "【詳細】" not in text:
        return text

    summary_part, detail_part = text.split("【詳細】", 1)
    items = dict(split_numbered_items(summary_part))

    for mark, item_text in items.items():
        detail_part = re.sub(
            rf"##\s*{mark}\s*.*",
            f"## {mark} {item_text}",
            detail_part,
            count=1,
        )

    return summary_part.strip() + "\n\n【詳細】\n" + detail_part.strip()


def needs_cross_comment(question: str) -> bool:
    keywords = [
        "相互のコメント",
        "相互コメント",
        "相手のコメント",
        "相手の見解",
        "相手の意見",
        "相手の回答を踏まえて",
        "お互いにコメント",
        "お互いのコメント",
        "お互いの見解",
        "互いの見解",
        "相互の見解",
        "双方の見解",
        "双方にコメント",
        "双方コメント",
        "見解にコメント",
        "コメントして",
        "コメントをして",
        "反論",
    ]
    return any(k in question for k in keywords)


def build_context() -> str:
    if not st.session_state.turns:
        return ""

    context = "これまでの討論履歴:\n"
    for i, turn in enumerate(st.session_state.turns, start=1):
        context += f"\n--- Turn {i} ---\n"
        context += f"質問: {turn['question']}\n"
        if turn.get("chatgpt"):
            context += f"ChatGPT回答: {turn['chatgpt']}\n"
        if turn.get("gemini"):
            context += f"Gemini回答: {turn['gemini']}\n"
        if turn.get("diff"):
            context += f"差分: {turn['diff']}\n"
        if turn.get("chatgpt_cross"):
            context += f"ChatGPTクロスコメント: {turn['chatgpt_cross']}\n"
        if turn.get("gemini_cross"):
            context += f"Geminiクロスコメント: {turn['gemini_cross']}\n"

    return context


def build_answer_prompt(question: str, context_snapshot: str = "") -> str:
    context_text = context_snapshot if context_snapshot is not None else ""
    return f"""{ANSWER_INSTRUCTION}

{context_text}

今回の質問:
{question}
"""


def build_diff_prompt(question: str, chatgpt_summary: str, gemini_summary: str) -> str:
    return f"""{DIFF_INSTRUCTION}

元の質問:
{question}

ChatGPT要点:
{chatgpt_summary}

Gemini要点:
{gemini_summary}
"""


def build_cross_prompt(original_question: str, own_answer: str, other_answer: str, other_name: str) -> str:
    return f"""{CROSS_COMMENT_INSTRUCTION}

元の質問:
{original_question}

自分の回答:
{own_answer}

{other_name}の回答:
{other_answer}

上記の{other_name}の回答に対して、見解を示してください。
"""


def call_openai_with_prompt(prompt: str, system_instruction: str):
    if not OPENAI_API_KEY or OPENAI_API_KEY == "PASTE_YOUR_OPENAI_API_KEY_HERE":
        return "OpenAI APIキーが未設定です。api_keys.py の OPENAI_API_KEY にキーを入れてください。", "未設定"

    last_error = None

    for model in OPENAI_MODELS:
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": prompt},
                    ],
                },
                timeout=120,
            )

            data = response.json()

            if "error" in data:
                last_error = data["error"]
                code = data["error"].get("code")
                if code == "invalid_api_key":
                    return "OpenAI APIキーが無効です。api_keys.py のキーを確認してください。", model
                if code == "insufficient_quota":
                    return f"OpenAI APIの利用上限に達しています。追加課金してください。\n{OPENAI_BILLING_URL}", model
                continue

            return data["choices"][0]["message"]["content"], model

        except Exception as e:
            last_error = str(e)
            continue

    return f"OpenAIの全モデル呼び出しに失敗しました。\n最後のエラー：{last_error}", "N/A"


def call_openai(question: str, context_snapshot: str = ""):
    return call_openai_with_prompt(build_answer_prompt(question, context_snapshot), ANSWER_INSTRUCTION)


def call_diff(question: str, chatgpt_summary: str, gemini_summary: str):
    prompt = build_diff_prompt(question, chatgpt_summary, gemini_summary)
    return call_openai_with_prompt(prompt, DIFF_INSTRUCTION)


def call_openai_cross(original_question: str, chatgpt_answer: str, gemini_answer: str):
    prompt = build_cross_prompt(original_question, chatgpt_answer, gemini_answer, "Gemini")
    return call_openai_with_prompt(prompt, CROSS_COMMENT_INSTRUCTION)


def call_gemini_with_prompt(prompt: str):
    if not GEMINI_API_KEY or GEMINI_API_KEY == "PASTE_YOUR_GEMINI_API_KEY_HERE":
        return "Gemini APIキーが未設定です。api_keys.py の GEMINI_API_KEY にキーを入れてください。", "未設定"

    last_error = None

    for model in GEMINI_MODELS:
        try:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=120,
            )

            try:
                data = response.json()
            except Exception:
                last_error = f"{model}: JSONとして読めない応答です。status={response.status_code}"
                continue

            if response.status_code >= 400:
                last_error = data.get("error", {"message": f"HTTP {response.status_code}"})
                continue

            if "error" in data:
                last_error = data["error"]
                message = data["error"].get("message", "")
                if "API key not valid" in message:
                    return "Gemini APIキーが無効です。api_keys.py のキーを確認してください。", model
                if "reported as leaked" in message:
                    return "Gemini APIキーが漏洩扱いで停止されています。新しいキーを作って api_keys.py に貼り直してください。", model
                # モデル未対応・quota・一時エラー等は次候補へフォールバック
                continue

            candidates = data.get("candidates")
            if not candidates:
                last_error = f"{model}: candidates がありません。応答={data}"
                continue

            try:
                parts = candidates[0]["content"]["parts"]
                if not parts:
                    last_error = f"{model}: parts が空です。応答={data}"
                    continue
                return parts[0].get("text", ""), model
            except Exception as e:
                last_error = f"{model}: 応答形式を読めません。error={e} / 応答={data}"
                continue

        except Exception as e:
            last_error = f"{model}: {e}"
            continue

    return f"Geminiの全モデル呼び出しに失敗しました。\n最後のエラー：{last_error}", "N/A"

def call_gemini(question: str, context_snapshot: str = ""):
    return call_gemini_with_prompt(build_answer_prompt(question, context_snapshot))


def call_gemini_cross(original_question: str, gemini_answer: str, chatgpt_answer: str):
    prompt = build_cross_prompt(original_question, gemini_answer, chatgpt_answer, "ChatGPT")
    return call_gemini_with_prompt(prompt)


def get_answer_bundle(ai_name: str, question: str, context_snapshot: str = ""):
    """初回回答の並列実行用。Streamlitのsession_stateはここでは読まない。"""
    if ai_name == "chatgpt":
        answer, model = call_openai(question, context_snapshot)
    elif ai_name == "gemini":
        answer, model = call_gemini(question, context_snapshot)
    else:
        answer, model = "", ""

    return {
        "answer": answer,
        "model": model,
        "summary": extract_summary(answer),
        "detail": extract_detail(answer),
    }


def render_cross_block(text: str):
    """相互見解カード用。要点はHTMLで①②③を縦並び、詳細は通常サイズの小見出し付きで表示する。"""
    if not text:
        return

    if "【詳細】" in text:
        summary_part, detail_part = text.split("【詳細】", 1)

        st.markdown('<div class="answer-subtitle">要点</div>', unsafe_allow_html=True)
        render_numbered_block(summary_part)

        st.markdown('<div class="answer-subtitle">詳細</div>', unsafe_allow_html=True)
        st.markdown(detail_part.strip())
    else:
        st.markdown('<div class="answer-subtitle">要点</div>', unsafe_allow_html=True)
        render_numbered_block(text)


def render_card(title: str, text: str, model: str = "", css_class: str = ""):
    st.markdown(f'<div class="answer-card {css_class}">', unsafe_allow_html=True)
    st.markdown(f'<div class="answer-title">{html.escape(title)}</div>', unsafe_allow_html=True)
    if model:
        st.markdown(f'<div class="answer-model">使用モデル：{html.escape(model)}</div>', unsafe_allow_html=True)

    if css_class == "cross":
        render_cross_block(text)
    elif "要点" in title:
        render_numbered_block(text)
    elif title in ["差分", "一致点と相違点"]:
        render_diff_block(text)
    else:
        st.markdown(align_detail_headings_to_summary(text))

    st.markdown("</div>", unsafe_allow_html=True)

def render_card_smooth(title: str, text: str, model: str = "", css_class: str = ""):
    """擬似ストリーミング：カードを少し遅延表示して、順に出てくる見た目にする。"""
    time.sleep(0.12)
    render_card(title, text, model, css_class)


with st.sidebar:
    st.markdown("### 実行モード")

    mode = st.radio(
        "",
        ["Multi", "Single"],
        horizontal=True,
        label_visibility="collapsed",
        key="execution_mode",
    )

    if mode == "Multi":
        target = "両方"
        diff_enabled = True

        multi_mode = st.radio(
            "Multiの使い方",
            ["独立回答", "相互見解"],
            horizontal=True,
            key="multi_mode",
        )

    else:
        single_ai = st.radio(
            "Singleで使うAI",
            ["ChatGPT", "Gemini"],
            horizontal=True,
            key="single_ai",
        )
        if single_ai == "ChatGPT":
            target = "ChatGPTのみ"
        else:
            target = "Geminiのみ"

        diff_enabled = False
        multi_mode = "独立回答"

    if st.button("履歴をクリア", use_container_width=True):
        st.session_state.turns = []
        st.rerun()


for turn in st.session_state.turns:
    st.markdown(f'<div class="user-box">{html.escape(turn["question"])}</div>', unsafe_allow_html=True)

    if turn.get("chatgpt_summary"):
        render_card("ChatGPT 要点", turn["chatgpt_summary"], turn.get("chatgpt_model", ""), "chatgpt")

    if turn.get("gemini_summary"):
        render_card("Gemini 要点", turn["gemini_summary"], turn.get("gemini_model", ""), "gemini")

    if turn.get("diff"):
        render_card("一致点と相違点", turn["diff"], turn.get("diff_model", ""), "diff")

    if turn.get("chatgpt_cross"):
        render_card("ChatGPT → Geminiへの見解", turn["chatgpt_cross"], turn.get("chatgpt_cross_model", ""), "cross")

    if turn.get("gemini_cross"):
        render_card("Gemini → ChatGPTへの見解", turn["gemini_cross"], turn.get("gemini_cross_model", ""), "cross")

    if not (turn.get("chatgpt_cross") or turn.get("gemini_cross")):

        if turn.get("chatgpt_detail"):
            render_card("ChatGPT 詳細", turn["chatgpt_detail"], turn.get("chatgpt_model", ""), "chatgpt")

        if turn.get("gemini_detail"):
            render_card("Gemini 詳細", turn["gemini_detail"], turn.get("gemini_model", ""), "gemini")


question = st.chat_input("質問を入力...（Enterで送信）")

if question:
    st.markdown(f'<div class="user-box">{html.escape(question)}</div>', unsafe_allow_html=True)

    chatgpt_answer = ""
    chatgpt_model = ""
    chatgpt_summary = ""
    chatgpt_detail = ""

    gemini_answer = ""
    gemini_model = ""
    gemini_summary = ""
    gemini_detail = ""

    diff_answer = ""
    diff_model = ""

    chatgpt_cross = ""
    chatgpt_cross_model = ""
    gemini_cross = ""
    gemini_cross_model = ""

    # 並列処理内で st.session_state を読まないため、
    # メイン処理側で履歴コンテキストを固定してからAPIに渡す。
    context_snapshot = build_context()

    if target == "両方":
        with st.spinner("ChatGPTとGeminiに問い合わせ中..."):
            with ThreadPoolExecutor(max_workers=2) as executor:
                future_chatgpt = executor.submit(get_answer_bundle, "chatgpt", question, context_snapshot)
                future_gemini = executor.submit(get_answer_bundle, "gemini", question, context_snapshot)

                chatgpt_result = future_chatgpt.result()
                gemini_result = future_gemini.result()

            chatgpt_answer = chatgpt_result["answer"]
            chatgpt_model = chatgpt_result["model"]
            chatgpt_summary = chatgpt_result["summary"]
            chatgpt_detail = chatgpt_result["detail"]

            gemini_answer = gemini_result["answer"]
            gemini_model = gemini_result["model"]
            gemini_summary = gemini_result["summary"]
            gemini_detail = gemini_result["detail"]

    elif target == "ChatGPTのみ":
        with st.spinner("ChatGPTに問い合わせ中..."):
            chatgpt_result = get_answer_bundle("chatgpt", question, context_snapshot)
            chatgpt_answer = chatgpt_result["answer"]
            chatgpt_model = chatgpt_result["model"]
            chatgpt_summary = chatgpt_result["summary"]
            chatgpt_detail = chatgpt_result["detail"]

    elif target == "Geminiのみ":
        with st.spinner("Geminiに問い合わせ中..."):
            gemini_result = get_answer_bundle("gemini", question, context_snapshot)
            gemini_answer = gemini_result["answer"]
            gemini_model = gemini_result["model"]
            gemini_summary = gemini_result["summary"]
            gemini_detail = gemini_result["detail"]

    cross_mode = (
        target == "両方"
        and multi_mode == "相互見解"
        and chatgpt_answer
        and gemini_answer
    )

    # 通常モード
    if not cross_mode:

        if chatgpt_summary:
            render_card_smooth("ChatGPT 要点", chatgpt_summary, chatgpt_model, "chatgpt")

        if gemini_summary:
            render_card_smooth("Gemini 要点", gemini_summary, gemini_model, "gemini")

        if target == "両方" and diff_enabled and chatgpt_summary and gemini_summary:
            with st.spinner("一致点と相違点を作成中..."):
                diff_answer, diff_model = call_diff(question, chatgpt_summary, gemini_summary)

            render_card_smooth("一致点と相違点", diff_answer, diff_model, "diff")

        if chatgpt_detail:
            render_card_smooth("ChatGPT 詳細", chatgpt_detail, chatgpt_model, "chatgpt")

        if gemini_detail:
            render_card_smooth("Gemini 詳細", gemini_detail, gemini_model, "gemini")

    # 相互見解モード
    else:

        with st.spinner("相互コメントを作成中..."):
            chatgpt_cross, chatgpt_cross_model = call_openai_cross(
                question,
                chatgpt_answer,
                gemini_answer,
            )

            gemini_cross, gemini_cross_model = call_gemini_cross(
                question,
                gemini_answer,
                chatgpt_answer,
            )

        render_card_smooth(
            "ChatGPT → Geminiへの見解",
            chatgpt_cross,
            chatgpt_cross_model,
            "cross",
        )

        render_card_smooth(
            "Gemini → ChatGPTへの見解",
            gemini_cross,
            gemini_cross_model,
            "cross",
        )

    st.session_state.turns.append(
        {
            "question": question,
            "target": target,
            "multi_mode": multi_mode,
            "chatgpt": chatgpt_answer,
            "chatgpt_model": chatgpt_model,
            "chatgpt_summary": chatgpt_summary,
            "chatgpt_detail": chatgpt_detail,
            "gemini": gemini_answer,
            "gemini_model": gemini_model,
            "gemini_summary": gemini_summary,
            "gemini_detail": gemini_detail,
            "diff": diff_answer,
            "diff_model": diff_model,
            "chatgpt_cross": chatgpt_cross,
            "chatgpt_cross_model": chatgpt_cross_model,
            "gemini_cross": gemini_cross,
            "gemini_cross_model": gemini_cross_model,
        }
    )

    # 質問送信後もサイドバーは自動で隠さない。
