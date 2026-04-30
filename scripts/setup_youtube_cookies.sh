#!/bin/bash
# setup_youtube_cookies.sh — Export YouTube cookies to bypass IP blocks
#
# YouTube blocks cloud/VPS IPs from fetching transcripts. Authenticated
# cookies from a real browser session bypass this restriction.
#
# METHOD 1: yt-dlp (recommended — automatic)
#   Install yt-dlp if not present, extract cookies from your Chrome browser.
#   Run this on a machine where you're logged into YouTube in Chrome.
#
# METHOD 2: Browser extension (manual)
#   Install "Get cookies.txt LOCALLY" Chrome extension
#   Go to youtube.com (make sure you're logged in)
#   Click the extension icon → Export → Save as youtube_cookies.txt
#   Copy to: config/youtube_cookies.txt
#
# METHOD 3: Copy from another machine
#   If you have a desktop/laptop where you're logged into YouTube,
#   export cookies there and scp to the server:
#   scp youtube_cookies.txt ms01-openclaw:~/trade-ai-v12-rebuild/trade-ai-v12-rebuild/config/

set -e
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
COOKIE_FILE="$PROJ/config/youtube_cookies.txt"

echo "=== YouTube Cookie Setup ==="
echo ""

# Check if cookies already exist
if [ -f "$COOKIE_FILE" ]; then
    LINES=$(wc -l < "$COOKIE_FILE")
    echo "Cookie file exists: $COOKIE_FILE ($LINES lines)"
    echo "To refresh: delete it and re-run this script"
    echo ""
    echo "Testing cookies..."
    cd "$PROJ"
    .venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
from youtube_transcript_ingest import _load_cookie_session, fetch_transcript
session = _load_cookie_session()
if session:
    print('Cookie session loaded successfully')
    r = fetch_transcript('dQw4w9WgXcQ')  # Rick Astley — always has captions
    if r.get('text'):
        print(f'Transcript fetch: SUCCESS ({r[\"segments\"]} segments, {r[\"duration_seconds\"]}s)')
    else:
        print(f'Transcript fetch: FAILED — {r.get(\"error\",\"unknown\")}')
        print('Cookies may be expired. Re-export from browser.')
else:
    print('ERROR: Could not load cookie session')
"
    exit 0
fi

echo "No cookie file found at: $COOKIE_FILE"
echo ""

# Try yt-dlp method — writes to a TEMP file, never overwrites auth cookies
if command -v yt-dlp &>/dev/null; then
    echo "yt-dlp found. Attempting cookie export from Chrome..."
    TEMP_COOKIE="/tmp/yt-cookie-export-$$.txt"
    yt-dlp --cookies-from-browser chrome --cookies "$TEMP_COOKIE" --skip-download "https://www.youtube.com/watch?v=dQw4w9WgXcQ" 2>/dev/null
    if [ -f "$TEMP_COOKIE" ] && grep -q "SID\|LOGIN_INFO" "$TEMP_COOKIE" 2>/dev/null; then
        cp "$TEMP_COOKIE" "$COOKIE_FILE"
        echo "Auth cookies exported to $COOKIE_FILE"
    elif [ -f "$TEMP_COOKIE" ]; then
        echo "WARNING: Exported cookies don't have SID/LOGIN_INFO — not using them"
        echo "You need to be logged into YouTube in Chrome for auth cookies"
        rm -f "$TEMP_COOKIE"
    fi
    if [ -f "$COOKIE_FILE" ]; then
        LINES=$(wc -l < "$COOKIE_FILE")
        echo "Cookies exported: $COOKIE_FILE ($LINES lines)"
    else
        echo "yt-dlp export failed. Try manual method below."
    fi
else
    echo "yt-dlp not installed."
    echo ""
    echo "=== MANUAL SETUP ==="
    echo ""
    echo "Option A: Install yt-dlp and retry"
    echo "  pip install yt-dlp"
    echo "  bash scripts/setup_youtube_cookies.sh"
    echo ""
    echo "Option B: Browser extension"
    echo "  1. Install 'Get cookies.txt LOCALLY' Chrome extension"
    echo "  2. Go to youtube.com (logged in)"
    echo "  3. Click extension → Export"
    echo "  4. Save as: $COOKIE_FILE"
    echo ""
    echo "Option C: Export from another machine"
    echo "  On a machine with Chrome logged into YouTube:"
    echo "    pip install yt-dlp"
    echo "    yt-dlp --cookies-from-browser chrome --cookies youtube_cookies.txt --skip-download https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    echo "    scp youtube_cookies.txt $(whoami)@$(hostname):$COOKIE_FILE"
fi

echo ""
echo "After adding cookies, test with:"
echo "  python3 scripts/youtube_transcript_ingest.py --test"
