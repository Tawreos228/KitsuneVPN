"""Постит (или редактирует) GitHub-релиз в Telegram-канал @Kitsune_VPN.

Использование:
    python scripts/notify_telegram.py                       # latest release
    python scripts/notify_telegram.py v0.2.1                # конкретный тег
    python scripts/notify_telegram.py v0.2.1 --edit 3       # переписать пост id=3
    python scripts/notify_telegram.py --selftest            # прогнать unit-тесты конвертера

Токен:
    Читается из переменной окружения KITSUNE_TG_TOKEN.
    Никогда не передаётся аргументом и не пишется в код.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO    = "Tawreos228/KitsuneVPN"
CHANNEL = "@Kitsune_VPN"
GH_API  = "https://api.github.com"
TG_API  = "https://api.telegram.org"

# Telegram MarkdownV2 спецсимволы которые НУЖНО экранировать в plain-тексте.
_MD_ESC_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def _escape_plain(text: str) -> str:
    """Экранировать спецсимволы Telegram MarkdownV2 в plain-тексте."""
    return _MD_ESC_RE.sub(r"\\\1", text)


def _escape_code(text: str) -> str:
    """Внутри ` ... ` или ``` ... ``` нужно экранировать только ` и \\."""
    return text.replace("\\", "\\\\").replace("`", "\\`")


def _escape_url(text: str) -> str:
    """Внутри (url) экранируем только ) и \\."""
    return text.replace("\\", "\\\\").replace(")", "\\)")


# ── GH markdown → TG MarkdownV2 ─────────────────────────────────────────────
# Принцип: tokenize формат-сегменты (code-blocks, inline-code, bold, italic,
# links, headers, lists), затем собираем выход чередуя escape-нутый plain
# текст и преобразованные сегменты.

# Порядок паттернов критичен: code-блок раньше inline-code, **bold** раньше
# *italic*, потому что ** включает *.
_TOKENS = [
    # (название, regex; captures зависят от типа)
    ("code_block", re.compile(r"```([^\n`]*)\n?(.*?)```", re.DOTALL)),
    ("inline_code", re.compile(r"`([^`\n]+)`")),
    ("bold",       re.compile(r"\*\*([^*\n]+)\*\*")),
    ("bold_alt",   re.compile(r"__([^_\n]+)__")),
    ("strike",     re.compile(r"~~([^~\n]+)~~")),
    ("link",       re.compile(r"\[([^\]]+)\]\(([^)]+)\)")),
    ("italic",     re.compile(r"(?<![*_\w])\*([^*\n]+)\*(?![*_\w])")),
    ("italic_alt", re.compile(r"(?<![*_\w])_([^_\n]+)_(?![*_\w])")),
]


def _render_token(kind: str, m: re.Match) -> str:
    """Преобразовать матч GH-markdown в TG MarkdownV2 фрагмент."""
    if kind == "code_block":
        lang = m.group(1).strip()
        body = m.group(2)
        return "```" + (lang + "\n" if lang else "") + _escape_code(body) + "```"
    if kind == "inline_code":
        return "`" + _escape_code(m.group(1)) + "`"
    if kind in ("bold", "bold_alt"):
        return "*" + _convert_inline(m.group(1)) + "*"
    if kind == "strike":
        return "~" + _convert_inline(m.group(1)) + "~"
    if kind == "link":
        return "[" + _convert_inline(m.group(1)) + "](" + _escape_url(m.group(2)) + ")"
    if kind in ("italic", "italic_alt"):
        return "_" + _convert_inline(m.group(1)) + "_"
    return _escape_plain(m.group(0))


def _convert_inline(text: str) -> str:
    """Рекурсивная конвертация inline-markdown в TG MarkdownV2.
    Находит ВСЕ формат-токены, не пересекающиеся друг с другом, и собирает выход."""
    matches: list[tuple[int, int, str, re.Match]] = []
    for kind, pat in _TOKENS:
        for m in pat.finditer(text):
            matches.append((m.start(), m.end(), kind, m))
    # Сортируем по позиции; при пересечении побеждает первый встретившийся.
    matches.sort(key=lambda x: (x[0], -x[1]))
    out: list[str] = []
    cursor = 0
    used_ranges: list[tuple[int, int]] = []
    for start, end, kind, m in matches:
        # пересечение с уже использованным диапазоном — пропускаем
        if any(not (end <= u[0] or start >= u[1]) for u in used_ranges):
            continue
        if start < cursor:
            continue
        if start > cursor:
            out.append(_escape_plain(text[cursor:start]))
        out.append(_render_token(kind, m))
        used_ranges.append((start, end))
        cursor = end
    if cursor < len(text):
        out.append(_escape_plain(text[cursor:]))
    return "".join(out)


def gh_to_tg(text: str) -> str:
    """Конвертация GitHub release-notes markdown в Telegram MarkdownV2.
    Обрабатываются: code-блоки, inline-code, bold/italic, headers, lists,
    blockquotes, ссылки. Заголовки '#'/'##'/'###' все мапятся на жирный."""
    lines_out: list[str] = []
    in_code = False
    code_buf: list[str] = []
    code_lang = ""
    for line in text.splitlines():
        if not in_code:
            m = re.match(r"^```(\S*)\s*$", line)
            if m:
                in_code = True
                code_lang = m.group(1)
                code_buf = []
                continue
        else:
            if line.strip() == "```":
                content = "\n".join(code_buf)
                fence = "```" + (code_lang + "\n" if code_lang else "")
                lines_out.append(fence + _escape_code(content) + "```")
                in_code = False
                continue
            code_buf.append(line)
            continue

        # вне code-блока — построчная конвертация
        # heading: # / ## / ### → жирная строка
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            lines_out.append("*" + _convert_inline(h.group(2)) + "*")
            continue
        # blockquote
        if line.startswith("> "):
            lines_out.append(">" + _convert_inline(line[2:]))
            continue
        # unordered list `- `, `* `, `+ `
        ul = re.match(r"^(\s*)[\-\*\+]\s+(.+)$", line)
        if ul:
            indent = ul.group(1)
            lines_out.append(indent + "•  " + _convert_inline(ul.group(2)))
            continue
        # ordered list `1. `
        ol = re.match(r"^(\s*)(\d+)\.\s+(.+)$", line)
        if ol:
            lines_out.append(ol.group(1) + ol.group(2) + "\\.  " + _convert_inline(ol.group(3)))
            continue
        # обычная строка с inline-формат
        lines_out.append(_convert_inline(line))
    return "\n".join(lines_out)


# ── GitHub release & Telegram API ──────────────────────────────────────────


def gh_release(tag: str | None) -> dict:
    url = f"{GH_API}/repos/{REPO}/releases/" + (f"tags/{tag}" if tag else "latest")
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "Kitsune-Telegram-Notifier/1.0",
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def assets_by_name(rel: dict) -> dict[str, str]:
    return {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}


def format_post(rel: dict) -> str:
    tag = rel["tag_name"]
    name = (rel.get("name") or tag).strip()
    body = (rel.get("body") or "").strip()
    title = f"🦊  *Kitsune {_escape_plain(tag)}*"
    if name and name != tag and not name.startswith(tag):
        # имя релиза часто формата "Kitsune v0.2.1 — critical hotfix: …"
        # вырезаем дублирующий "Kitsune vX.Y.Z — " префикс для краткости
        subtitle = re.sub(r"^Kitsune\s+" + re.escape(tag) + r"\s*[—\-:]?\s*", "", name).strip()
        if subtitle:
            title += f"\n_{_escape_plain(subtitle)}_"
    body_tg = gh_to_tg(body)
    # запас под кнопки + заголовок — 4096 общий лимит
    if len(body_tg) > 3500:
        body_tg = body_tg[:3490].rstrip() + "\n\n…"
    return title + "\n\n" + body_tg


def build_keyboard(rel: dict) -> dict:
    assets = assets_by_name(rel)
    setup    = next((u for n, u in assets.items() if n.lower().endswith(".exe")), None)
    portable = next((u for n, u in assets.items() if n.lower().endswith(".zip")), None)
    rows = []
    if setup:    rows.append([{"text": "📥 Установщик (.exe)", "url": setup}])
    if portable: rows.append([{"text": "📦 Portable (.zip)",    "url": portable}])
    rows.append([{"text": "📝 Подробнее на GitHub", "url": rel["html_url"]}])
    return {"inline_keyboard": rows}


def tg_call(token: str, method: str, payload: dict) -> dict:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(f"{TG_API}/bot{token}/{method}", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"Telegram API HTTP {e.code}: {body}") from e


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--selftest":
        return _run_selftests()
    tag: str | None = None
    edit_id: int | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--edit":
            i += 1
            if i >= len(argv):
                print("ERROR: --edit требует номер message_id", file=sys.stderr); return 2
            edit_id = int(argv[i])
        elif not tag:
            tag = a
        else:
            print(f"ERROR: лишний аргумент {a!r}", file=sys.stderr); return 2
        i += 1

    token = os.environ.get("KITSUNE_TG_TOKEN", "").strip()
    if not token:
        print("ERROR: KITSUNE_TG_TOKEN не задан в окружении", file=sys.stderr)
        return 2
    try:
        rel = gh_release(tag)
    except Exception as e:
        print(f"ERROR: GitHub API: {e}", file=sys.stderr); return 3
    print(f"→ release: {rel['tag_name']} — {rel.get('name','')}")
    text = format_post(rel)
    kb = build_keyboard(rel)
    payload = {
        "chat_id": CHANNEL,
        "text": text,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": "true",
        "reply_markup": json.dumps(kb, ensure_ascii=False),
    }
    if edit_id is not None:
        payload["message_id"] = edit_id
        method = "editMessageText"
    else:
        method = "sendMessage"
    try:
        resp = tg_call(token, method, payload)
    except Exception as e:
        # Идемпотентный edit (контент идентичен текущему) — Telegram возвращает HTTP 400
        # "message is not modified". Это НЕ ошибка — это no-op success.
        if edit_id is not None and "message is not modified" in str(e):
            print(f"✓ no-op edit (message {edit_id} already has this exact content) — {CHANNEL}")
            return 0
        print(f"ERROR: Telegram: {e}", file=sys.stderr); return 4
    if not resp.get("ok"):
        print(f"ERROR: Telegram non-ok: {resp}", file=sys.stderr); return 5
    msg_id = resp["result"]["message_id"]
    verb = "edited" if edit_id is not None else "posted to"
    print(f"✓ {verb} {CHANNEL} — message_id={msg_id}")
    print(f"  link: https://t.me/Kitsune_VPN/{msg_id}")
    return 0


# ── inline-тесты конвертера ────────────────────────────────────────────────


def _run_selftests() -> int:
    cases = [
        # (вход, ожидаемый выход, описание)
        ("plain text",                "plain text",                "no markdown"),
        ("**bold**",                  "*bold*",                    "bold"),
        ("__also bold__",             "*also bold*",               "bold via underscores"),
        ("*italic*",                  "_italic_",                  "italic single asterisk"),
        ("_alt italic_",              "_alt italic_",              "italic via underscore"),
        ("`inline code`",             "`inline code`",             "inline code"),
        ("text with `code` inside",   "text with `code` inside",   "code in plain"),
        ("[link](https://x.com)",     "[link](https://x.com)",     "simple link"),
        ("**bold with . dot**",       "*bold with \\. dot*",        "escape inside bold"),
        ("# Heading",                 "*Heading*",                 "h1"),
        ("## Sub heading",            "*Sub heading*",             "h2"),
        ("- item one",                "•  item one",               "list item"),
        ("- **bold item**",           "•  *bold item*",            "list with inline bold"),
        ("1. first ordered",          "1\\.  first ordered",        "ordered list"),
        ("normal . dash - text",      "normal \\. dash \\- text",   "escape plain"),
        ("> quoted line",             ">quoted line",              "blockquote"),
        ("```\ncode block\n```",      "```code block```",          "code block no lang"),
        ("```py\nx = 1\n```",         "```py\nx = 1```",            "code block with lang (= is plain inside code)"),
        ("```\nbacktick: ` here\n```", "```backtick: \\` here```",   "escape backtick inside code"),
        ("**bold** and *italic*",     "*bold* and _italic_",        "mixed bold + italic in one line"),
        ("plain text with [link](https://t.me/x) inline",
                                      "plain text with [link](https://t.me/x) inline",
                                      "link inside plain text (url is not escape-able beyond \\) and \\\\)"),
    ]
    failed = 0
    for src, expected, desc in cases:
        actual = gh_to_tg(src)
        if actual == expected:
            print(f"  [OK]   {desc}")
        else:
            failed += 1
            print(f"  [FAIL] {desc}")
            print(f"         input:    {src!r}")
            print(f"         expected: {expected!r}")
            print(f"         actual:   {actual!r}")
    print(f"\n{len(cases) - failed}/{len(cases)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
