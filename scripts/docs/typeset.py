"""Typesetting of the Markdown docs for GitHub: justified text with automatic hyphenation.

GitHub removes CSS (no text-align, no hyphens: auto), but keeps the align attribute of a <div> and
soft hyphens (U+00AD). So the document is wrapped in <div align="justify"> and long words of the
running text get soft hyphens from a hyphenation dictionary; the browser breaks there only when a
line needs it (user, 2026-09-28).

    python scripts/docs/typeset.py docs/TUTORIAL.md [more.md ...] [--lang en_US] [--strip]

Idempotent: old soft hyphens are removed first, then set again. --strip only removes them and the
wrapper. Never hyphenated: code blocks and `code`, links and pictures, HTML tags and comments,
headings, table rows, and words with digits, underscores, dots or slashes (file names).
Needs: pip install pyphen"""
import re, sys

SHY = "­"
OPEN, CLOSE = '<div align="justify">', "</div>"
MIN_WORD = 8
PROTECT = re.compile(r"`[^`]*`"                      # inline code
                     r"|!\[[^\]]*\]\([^)]*\)"        # pictures
                     r"|\]\([^)]*\)"                 # link targets
                     r"|<[^>]*>"                     # HTML tags
                     r"|https?://\S+")               # bare URLs
WORD = re.compile(r"(?<![\w/.\\-])[A-Za-z]{%d,}(?![\w/.\\-])" % MIN_WORD)   # not beside - (names)


def hyphenate_text(text, dic):
    return WORD.sub(lambda m: dic.inserted(m.group(0), hyphen=SHY), text)


def hyphenate_line(line, dic):
    out, pos = [], 0
    for m in PROTECT.finditer(line):
        out.append(hyphenate_text(line[pos:m.start()], dic))
        out.append(m.group(0))
        pos = m.end()
    out.append(hyphenate_text(line[pos:], dic))
    return "".join(out)


def unwrap(text):
    lines = text.split("\n")
    if lines and lines[0].strip() == OPEN:
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip() == CLOSE:
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
    return "\n".join(lines) + "\n"


def typeset(text, dic):
    text = unwrap(text.replace(SHY, ""))
    out, fence, comment = [], False, False
    for line in text.split("\n"):
        s = line.lstrip()
        if s.startswith("```") or s.startswith("~~~"):
            fence = not fence
            out.append(line)
            continue
        if fence:
            out.append(line)
            continue
        if comment or s.startswith("<!--"):
            comment = "-->" not in line if not comment else "-->" not in line
            out.append(line)
            continue
        if s.startswith("#") or s.startswith("|"):
            out.append(line)
            continue
        out.append(hyphenate_line(line, dic))
    body = "\n".join(out).rstrip("\n")
    return f"{OPEN}\n\n{body}\n\n{CLOSE}\n"


def main(argv):
    lang = argv[argv.index("--lang") + 1] if "--lang" in argv else "en_US"
    files = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--lang")]
    dic = None
    if "--strip" not in argv:
        import pyphen
        dic = pyphen.Pyphen(lang=lang, left=3, right=3)
    for path in files:
        text = open(path, encoding="utf-8").read()
        new = unwrap(text.replace(SHY, "")) if dic is None else typeset(text, dic)
        open(path, "w", encoding="utf-8", newline="\n").write(new)
        print(f"{path}: {new.count(SHY)} soft hyphens")


if __name__ == "__main__":
    main(sys.argv[1:])
