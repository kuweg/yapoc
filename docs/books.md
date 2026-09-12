# Books library and reading companion

Open **Books** in the Workspace sidebar and upload a PDF or EPUB (up to 50 MB).
The library stores the original file, extracted source locations, reading
progress, appearance preferences, bookmarks, highlights, notes and conversations
locally under `data/books` and the existing SQLite database. Upload runs extraction
off the API event loop; an extraction indicator remains visible until ready.
No additional dependencies or Google account are required.

## Reading

Open a cover to resume. PDF locations are physical file pages; printed page
labels are also displayed when present. EPUB locations follow the package spine
(chapter order), with a saved relative scroll position inside the chapter. EPUB
content is rendered as extracted text, never executed as uploaded HTML.

Use the **Pages / Vertical scroll** sliding switch above the text to choose one
location at a time or a continuous book. The mode and reading position are saved
per book. Continuous mode loads text near the viewport as you read; page/chapter
numbers, bookmarks and AI sources follow the visible location. Select text within
one page/chapter when highlighting or asking about a passage.

Use the contents drawer, book search, previous/next buttons or location field.
PDFs also offer an original-document view using the browser PDF viewer, including
its zoom and layout controls. Use the YAPOC location controls to save page changes;
the embedded browser viewer does not report internal page changes back to YAPOC.
Paper, sepia and dark themes, adjustable text size and full-screen focus are
available. Select text in text view to highlight it or ask about it. Bookmarks
and notes can be revisited from the drawer and exported as a reading journal.

## Reading assistant

The labeled **Open AI assistant / Hide AI assistant** button in the reader header
always remains available, including on mobile, after closing the right panel.

Choose current location, a range, entire book, or selected text. Questions use
only excerpts from that scope. Spoiler protection defaults on and caps retrieval
at the saved reading position. It also excludes conversation turns from later
locations. Disable it explicitly to discuss unread sections.

Long ranges are searched by question keywords; when no keywords match, excerpts
are distributed through the range. At most 18 passages are sent per question.
This is bounded lexical retrieval, not an exhaustive whole-book analysis or
semantic embedding index. The UI states when ranges may be sampled. Citations
map to actual supplied passages; fabricated citation IDs are marked unverified.
An existing citation does not itself prove that the model's claim is correct.

The companion uses the configured Master provider/model through the existing
adapter interface, without agent execution tools. Excerpts leave the machine
when that provider is remote. It does not silently switch providers. Failures
leave the library and progress intact and never return raw provider exceptions.
Model usage remains subject to that provider's pricing; this initial reader path
does not yet feed per-call token usage into YAPOC's agent cost dashboard.

Actions include explanation, summary, connections, flashcards, a one-question
comprehension check, and **Read with me**. Reading goal and available minutes
are configurable in **Reading goal & exports** and are passed to the guide.
Reply to a quiz in the same book conversation for feedback. **Listen** reads an
answer through browser speech synthesis; voice availability depends on the OS
and browser. There is no downloadable podcast-generation pipeline.

## YAPOC integration

- Save answers to Notes, including the book reference.
- Download the full reading journal or register it in Artifacts.
- Continue a discussion in main chat with explicit source locations.
- Request a Whiteboard concept map through the normal agent task flow.
- Type `@book:"Book title":pages:4-9` or `@book:<id>:pages:4-9` in chat.
  For EPUBs these numbers designate chapters. A bare book reference supplies
  excerpts through the saved position. Missing or ambiguous names fail clearly.
- Master, Planning, Builder and Researcher have `book_list` and `book_read`.
  Both runtime JSON and agent YAML configurations include those read-only tools.

## Current limits

Scanned PDF pages require OCR for AI; original PDFs remain readable. OCR,
embedded EPUB illustrations/styles, exact EPUB character anchors, publisher cover
extraction, draggable margin notes, semantic retrieval, and scheduled spaced
repetition are future extensions. Current covers are generated typographic
covers. Highlights use exact source text. Do not treat extracted tables,
equations or complex PDF layouts as exact reproductions; use Original PDF.

Validation: `poetry run pytest tests/test_books.py tests/test_db.py tests/test_whiteboard.py tests/test_agent_settings.py`
and `npm --prefix app/frontend run build`. Backend restart is required.

## Reading tools and knowledge shelf

- **Reading timeline:** drag the position slider or use its arrow keys to jump.
  Section ticks show the book structure; numbered diamond buttons open locations
  with bookmarks, highlights or notes. Hover a marker for its saved text.
- **Passage actions:** select text within one page/chapter for a floating
  Explain / Translate / Example / Highlight / Ask / Save menu. The selection
  toolbar remains available if scrolling dismisses the bubble. Translation uses
  the **From** and **To** language fields in the reading assistant. From defaults
  to **Auto-detect**; choose a suggestion or type any language in either field.
  Both choices are saved per book; existing target-language preferences are preserved. It uses the configured AI provider.
- **Explain differently:** Beginner, Technical, Analogy and Worked example control
  subsequent answers; choose a style and press Explain to reinterpret a passage.
  Style and translation language are saved per book. Illustrative analogies and
  examples are explicitly distinguished from source material.
- **Book → Whiteboard:** choose the assistant source range and open Create
  Whiteboard concept map. Generate a preview, inspect its source excerpts, name
  the canvas, and create it. It always creates a new canvas. Nodes keep the book
  ID, location, excerpt and `@book` reference; **Read source** on a Whiteboard card
  returns to that reading location. The existing Whiteboard editor and agent tools
  can expand the resulting map. Long ranges may be sampled; maps are AI
  interpretations and should be reviewed. Invalid citations/edges are rejected.
- **Study desk:** toggle the small pixel-art room in the reader header. The reader
  companion reads, types while AI is responding, and sleeps after 45 seconds of
  inactivity. A cat, lamp and bookshelf accompany it. It is off by default, saved
  per book, and respects reduced motion and inactive browser/app tabs.
- **Knowledge shelf:** open it from the Books library. Highlights and reading
  notes appear automatically across books. Save a selection with your own
  explanation, or use **Keep idea** on an AI answer. Search saved text and book
  titles, open its source, send it to Notes or a new Whiteboard, or remove it.
  The shelf shows 50 items per page and is backed by the existing local reading
  annotations, so removing an entry removes that annotation; deleting a book
  removes its shelf entries. Exported Notes and Whiteboards remain independent.

Reading tool checks:
`poetry run pytest -q tests/test_books.py tests/test_whiteboard.py tests/test_db.py`
and `poetry run python scripts/check_reading_tools_browser.py` (running backend
and frontend required; uses disposable fixtures and mocks AI responses).
