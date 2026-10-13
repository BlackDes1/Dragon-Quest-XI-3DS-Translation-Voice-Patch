"""30-column dialogue layout, with opaque control tokens and voice boundaries.

Returns pages for the future native writer. Pages are not new voice clips: one
PC table row remains one logical dialogue/voice cue. Unknown substitutions and
unmeasured long words fail explicitly instead of being clipped or discarded.
"""
import re
import struct

MAX_COLUMNS = 30
ROWS_PER_PAGE = 3
WIDTHS = {1: 8, 100: 0, 102: 0}
TOKEN = re.compile(r'\x04[\s\S]')
NAME_TAB_SHOW = re.compile(r'<nametab_show=[A-Za-z0-9_]+>')
# Only these characters are ignored by the native voice lookup. Python's
# generic \s also matches NBSP and Unicode separators, which are significant
# for that lookup. Keep them in words rather than silently deleting them.
WORDS = re.compile(r'(?:\x04[\s\S]|[^ \n\r\t\u3000])+')


class LayoutIdentityError(ValueError):
    """Reject a damaged layout, while allowing other rows to be diagnosed."""


def fingerprint(text):
    """Native whitespace-independent lookup key; not an input-file checksum."""
    values = struct.unpack('<'+'H'*(len(text.encode('utf-16le'))//2), text.encode('utf-16le'))
    h1, h2, length = 2166136261, 5381, 0
    for c in values:
        if c in (32, 10, 13, 9, 0x3000, 0xe100):
            continue
        if not c:
            raise ValueError('Embedded NUL')
        h1 = ((h1 ^ c)*16777619) & 0xffffffff
        h2 = (h2*33+c) & 0xffffffff
        length += 1
    return (h1, h2, length)


def visible_width(text):
    total, i = 0, 0
    while i < len(text):
        c = text[i]
        if c == '\x04':
            if i+1 == len(text) or ord(text[i+1]) not in WIDTHS:
                raise ValueError('Unmeasured dynamic substitution')
            total += WIDTHS[ord(text[i+1])]
            i += 2
            continue
        # U+E100 is accepted only as the leading layout/voice identity marker
        # handled by reflow(). An occurrence inside the visible body is an
        # actual private-use marker and must not be silently discarded.
        # Fullwidth punctuation/digits in PC tables are visible Unicode text,
        # not native markers. Only the Unicode Private Use Areas are rejected.
        codepoint = ord(c)
        if (0xe000 <= codepoint <= 0xf8ff or
                0xf0000 <= codepoint <= 0xffffd or
                0x100000 <= codepoint <= 0x10fffd):
            raise ValueError('Unexpected native marker in visible text')
        total += len(c.encode('utf-16le')) // 2
        i += 1
    return total


def reflow(text):
    # One native string/voice cue at a time. Never concatenate adjacent rows.
    prefix = '\ue100' if text.startswith('\ue100') else ''
    body = text[len(prefix):]
    if any(ord(c) < 32 and c not in '\n\r\t\x04\x01\x64\x66' for c in body):
        raise ValueError('Unsupported dialogue control')
    # Keep substitutions and their arguments atomic, then use the fewest rows
    # possible and balance those rows. Greedy wrapping left a short final row
    # even when its words could be moved to make both rows easier to read.
    words = WORDS.findall(body)
    if not words:
        return dict(text=text, pages=[], columns=MAX_COLUMNS,
                    rows_per_page=ROWS_PER_PAGE, fingerprint=list(fingerprint(text)))

    widths = [visible_width(word) for word in words]
    if any(width > MAX_COLUMNS for width in widths):
        raise ValueError('Word exceeds dialogue width')

    minimum_rows = 1
    current_width = 0
    has_word = False
    for width in widths:
        candidate = current_width + (1 if has_word else 0) + width
        if candidate > MAX_COLUMNS and has_word:
            minimum_rows += 1
            current_width = width
            has_word = True
        elif candidate > MAX_COLUMNS:
            raise ValueError('Word exceeds dialogue width')
        else:
            current_width = candidate
            has_word = True

    # Minimize the squared visible widths while keeping the minimum row count.
    # This produces full, balanced rows without inventing a new voice cue.
    inf = float('inf')
    costs = [[inf] * (len(words) + 1) for _ in range(minimum_rows + 1)]
    previous = [[None] * (len(words) + 1) for _ in range(minimum_rows + 1)]
    costs[0][0] = 0
    for row_count in range(1, minimum_rows + 1):
        for end in range(1, len(words) + 1):
            line_width = 0
            for start in range(end - 1, -1, -1):
                line_width += widths[start]
                if start < end - 1:
                    line_width += 1
                if line_width > MAX_COLUMNS:
                    break
                prior = costs[row_count - 1][start]
                if prior == inf:
                    continue
                candidate = prior + line_width * line_width
                if candidate < costs[row_count][end]:
                    costs[row_count][end] = candidate
                    previous[row_count][end] = start

    if costs[minimum_rows][len(words)] == inf:
        raise ValueError('Could not balance dialogue within the row width')
    lines = []
    end = len(words)
    for row_count in range(minimum_rows, 0, -1):
        start = previous[row_count][end]
        if start is None:
            raise ValueError('Could not reconstruct dialogue line breaks')
        lines.insert(0, ' '.join(words[start:end]))
        end = start
    if end:
        raise ValueError('Could not reconstruct dialogue line breaks')

    rendered = prefix+'\n'.join(lines)
    if fingerprint(rendered) != fingerprint(text) or TOKEN.findall(rendered) != TOKEN.findall(text):
        raise LayoutIdentityError('Reflow changed voice identity or control sequence')
    pages = [lines[i:i+ROWS_PER_PAGE] for i in range(0, len(lines), ROWS_PER_PAGE)]
    return dict(text=rendered, pages=pages, columns=MAX_COLUMNS, rows_per_page=ROWS_PER_PAGE,
                fingerprint=list(fingerprint(rendered)))


def from_pc(text):
    # Parse only known presentation tags. Event commands stay unresolved until
    # matched to a typed 3DS field with its own native control sequence.
    text = re.sub(r'^\s*\*\s*:\s*', '', text)
    # These tags control the PC speaker/name tab. The 3DS field stores the
    # speaker separately, so they are metadata rather than visible dialogue.
    # Keep the whitelist narrow: unknown tags still fail closed below.
    text = NAME_TAB_SHOW.sub('', text)
    text = text.replace('<nametab_hide>', '').replace('<end>', '')
    replacements = {'<pc>': '\x04\x01', '<LM_LF>': '\n', '<br>': ' ',
                    '<end>': '', '<LM_6>': '', '<LM_9>': '', '<LM_.|>': '...',
                    '<LM_--->': ' - '}
    for a, b in replacements.items():
        text = text.replace(a, b)
    if re.search(r'<[^>]*>', text):
        raise ValueError('PC event/presentation tag requires typed 3DS mapping')
    for a, b in (('’', "'"), ('‘', "'"), ('“', '"'), ('”', '"'), ('…', '...'), ('—', ' - '), ('–', '-')):
        text = text.replace(a, b)
    # Two ASCII dashes used for PC punctuation become one supported dash.
    text = text.replace('--', ' - ')
    return reflow(text)


def menu_label(text):
    return 'Monster List' if text.strip() == 'Defeated Monster List' else text
