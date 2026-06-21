import re
from html import escape


BUTTON_LINE_RE = re.compile(
    r"^\{\{\s*button\s*:\s*(?P<label>.+?)\s*\|\s*(?P<url>(?:https?://|mailto:)[^\s{}]+)\s*\}\}$",
    re.IGNORECASE,
)
INLINE_LINK_RE = re.compile(
    r"\[(?P<md_label>[^\]]+)\]\((?P<md_url>(?:https?://|mailto:)[^\s)]+)\)"
    r"|(?P<raw_url>(?:https?://|mailto:)[^\s<]+)",
    re.IGNORECASE,
)


def _render_inline_links(text):
    rendered = []
    last_index = 0

    for match in INLINE_LINK_RE.finditer(text):
        rendered.append(escape(text[last_index:match.start()]))
        if match.group('md_label') and match.group('md_url'):
            rendered.append(
                f'<a href="{escape(match.group("md_url"), quote=True)}" '
                'style="color:#2563eb;text-decoration:underline;">'
                f'{escape(match.group("md_label"))}</a>'
            )
        else:
            url = match.group('raw_url') or ''
            rendered.append(
                f'<a href="{escape(url, quote=True)}" '
                'style="color:#2563eb;text-decoration:underline;">'
                f'{escape(url)}</a>'
            )
        last_index = match.end()

    rendered.append(escape(text[last_index:]))
    return ''.join(rendered)


def _button_block(label, url):
    safe_label = escape(label.strip())
    safe_url = escape(url.strip(), quote=True)
    return (
        '<div style="margin:24px 0;text-align:center;">'
        f'<a href="{safe_url}" '
        'style="display:inline-block;background:#1663c7;color:#ffffff;'
        'text-decoration:none;font-weight:700;font-size:15px;line-height:1;'
        'padding:14px 22px;border-radius:999px;">'
        f'{safe_label}</a>'
        '</div>'
    )


def render_rich_email_html(subject, body, button_text=None, button_url=None):
    normalized = (body or '').replace('\r\n', '\n').replace('\r', '\n')
    blocks = []
    paragraph_lines = []

    def flush_paragraph():
        nonlocal paragraph_lines
        if paragraph_lines:
            blocks.append(
                '<p style="margin:0 0 16px;font-size:15px;line-height:1.75;color:#243b53;">'
                + '<br>'.join(paragraph_lines)
                + '</p>'
            )
            paragraph_lines = []

    for line in normalized.split('\n'):
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
            continue

        button_match = BUTTON_LINE_RE.match(stripped)
        if button_match:
            flush_paragraph()
            blocks.append(_button_block(button_match.group('label'), button_match.group('url')))
            continue

        paragraph_lines.append(_render_inline_links(stripped))

    flush_paragraph()

    if button_text and button_url:
        blocks.append(_button_block(button_text, button_url))

    if not blocks:
        blocks.append(
            '<p style="margin:0;font-size:15px;line-height:1.75;color:#243b53;">No message provided.</p>'
        )

    safe_subject = escape(subject or 'BSBCS message')
    return ''.join([
        '<!doctype html>',
        '<html>',
        '<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>',
        '<body style="margin:0;padding:24px 12px;background:#eef6fb;font-family:Arial,sans-serif;color:#10213b;">',
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:680px;margin:0 auto;border-collapse:collapse;">',
        '<tr><td style="padding:0 0 16px 0;text-align:center;">',
        '<div style="font-size:12px;font-weight:700;letter-spacing:0.28em;color:#0b7fab;text-transform:uppercase;">BSBCS</div>',
        f'<div style="margin-top:10px;font-size:28px;font-weight:800;line-height:1.2;color:#10213b;">{safe_subject}</div>',
        '</td></tr>',
        '<tr><td style="background:#ffffff;border:1px solid #cfe0f5;border-radius:24px;padding:32px;box-shadow:0 20px 40px rgba(15, 23, 42, 0.06);">',
        ''.join(blocks),
        '</td></tr>',
        '<tr><td style="padding:18px 8px 0 8px;text-align:center;font-size:12px;line-height:1.6;color:#5f7490;">',
        'This email was sent from the BSBCS dashboard.',
        '</td></tr>',
        '</table>',
        '</body></html>',
    ])
