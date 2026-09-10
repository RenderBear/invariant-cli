# Design language

The presentation reference for Invariant's two human surfaces: the explanatory document
[`model.html`](../protocol/model.html) and the terminal. It records tokens, scales, and component rules. The
machine and contributor contract lives in [`SPEC.md`](SPEC.md).

## Document palette

Monochrome. Five tokens.

| Token | Value | Use |
| --- | --- | --- |
| Ink | `#171717` | Body text, primary rules, strong borders |
| Muted | `#626262` | Supporting text, captions, secondary labels |
| Line | `#b8b8b8` | Table cells, ordinary diagram nodes, separators |
| Soft | `#eeeeec` | Table headers and limited semantic emphasis |
| Paper | `#ffffff` | Page and component background |

Fills stay light enough to print without consuming toner. State is never carried by fill alone.

## Typography

### Body

```css
-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif
```

- Size: `15px`
- Line height: `1.58`
- Colour: Ink; supporting copy Muted
- Measure: readable widths, never full-page lines

### Monospace

```css
ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace
```

Used for labels, identifiers, metadata, code, table headings, and diagram titles. Not a body face.

### Scale

| Element | Size | Treatment |
| --- | ---: | --- |
| Document title | `34px` | Semibold, compact line height |
| Section heading | `24px` | Bottom rule, generous top margin |
| Subsection heading | `18px` | Semibold |
| Card or node title | `13–15px` | Bold or semibold |
| Metadata and labels | `10–12px` | Monospace, often uppercase |

## Page geometry

- Content width: `1120px` maximum, single centred column
- Side margin: `20px` minimum
- Main top padding: `42px`
- Major section top margin: `64px`; sections separated by whitespace and one horizontal rule
- No sidebars, floating navigation, or dashboard chrome

## Document components

| Component | Background | Border | Notes |
| --- | --- | --- | --- |
| Header | Paper | Strong bottom rule | Status metadata, title, scope summary, compact contents |
| Table of contents | Soft or Paper | Thin Line | Two columns wide, one narrow; plain underlined links |
| Callout | Paper | `1px` Ink | Short bold label, then prose; no icon, shadow, or colour strip |
| Card | Paper | Thin Line, square corners | Repeated parallel concepts only; compact padding; no hover |
| Table | Soft header row | Collapsed | Monospace headers, left-aligned, horizontal scroll when narrow |
| Code and manifests | Very light gray | Thin Line | Monospace, no syntax colouring, copyable |

## Diagram language

Diagrams are semantic HTML laid out with Grid or Flexbox; never raster images.

| Node kind | Background | Border | Label |
| --- | --- | --- | --- |
| Default | Paper | `1px` Ink or Line, square | Bold title, optional muted description |
| Primary or terminal | Paper or Soft | `2px` Ink | Same typography |
| Derived or rebuildable | Paper or Soft | Dashed Ink or Line | Explicit `Derived`, `Projection`, or `Rebuildable` text |

- Connectors: Unicode arrows (`→`, `←`), short monospace labels above or beside, horizontal
  when practical; no routed lines, decorative arrowheads, or animation.
- Planes: one outer border each, plane name in a narrow monospace label column, contained modules
  separated by thin vertical rules; the primary plane gets a thicker border or Soft fill.
- Decisions: nodes phrased as direct questions; branches labelled `YES`, `NO`, or an explicit
  condition; the recommended terminal gets a `2px` border; overflow branches explained in prose.
- Captions: every diagram has one, stating the architectural meaning.

## Print

- Black text on white paper; no black panels, saturated fills, shadows, or textures.
- Borders and labels retain all meaning when fills disappear.
- Figures, tables, cards, and callouts carry `break-inside: avoid` where practical.
- No substantive content behind interactive controls.
- Link labels remain understandable without the URL.

## Responsive

- Prose and cards collapse to one column; contents collapse from two columns to one.
- Wide diagrams and tables scroll horizontally rather than compressing text.
- Reading order matches DOM order.

## Document exclusions

Reversed panels, diagonal lines, hatching, gradients, patterns, drop shadows, rounded dashboard
panels, marketing typography, decorative icons, multiple accent colours, sticky navigation,
animation, hover-dependent meaning, and diagrams whose semantics rely only on colour.

## README figures

SVG figures under `.github/assets/` follow the document palette with one addition.

| Token | Value | Use |
| --- | --- | --- |
| Accent | `#4f7d1b` | Glyph fills, and the arrows that carry accepted meaning |

- Glyphs are flat, single-colour, 48×48, with white cut-outs for detail; one glyph per concept,
  reused across figures (human, agent, domain, contract, sources, record, and the lifecycle stages).
- Boxes, planes, rules, and text use Ink, Muted, Line, Soft, and Paper as in the document.
- Ordinary arrows are Muted; dashed arrows mark loops and escalation; Accent arrows mark meaning
  entering or leaving repository memory.
- Figures are 1200 wide, carry a `<title>` and `<desc>`, and stay legible in grayscale.

## Terminal palette

Colour is expressed as ANSI attributes so the user's terminal theme supplies the actual hues.
Every attribute has exactly one role. The wordmark is the only bold, coloured element in a
result block; nothing else competes with it.

| Token | Attribute | Role |
| --- | --- | --- |
| Accent | `1;36` bold cyan | The `Invariant` wordmark, the connected agent's name and glyph, the user prompt, the next-action arrow and command callouts |
| Strong | `1` bold | The active option in a questionnaire, emphasis inside agent prose |
| Muted | `2` dim | Block titles, field labels, the turn rule, the spinner line, durations, hints |
| Ok | `32` green | Success block titles and trail marks; completed, ready, valid, landed states |
| Warn | `1;33` bold amber / `33` amber | Warnings, recommended options; waiting and in-progress states |
| Bad | `1;31` bold red | Failure marks; failed, invalid, stale, absent states |

Plain text is the default; nothing else is coloured. `NO_COLOR` disables every attribute, and
output that is not a terminal is emitted as the plain `NAME: value` records.

## Terminal glyphs

| Glyph | Meaning |
| --- | --- |
| `✓` | A step or command completed |
| `×` | A step or command failed |
| `!` | A warning |
| `→` | The single next action |
| `›` | Speech: after `(mode)` for the user, after `(provider)` for the agent; also a command to run |
| `─` | The turn rule between conversation turns |
| `·` | A separator between short facts on one line |
| `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` | Activity in progress |

## Terminal layout

Result block:

```text
Invariant  Repository                  accent wordmark, two spaces, muted title
  Status     needs attention           muted label column, value; state words toned
  Branch     main
  Change     cfB (implementing)        a repeated label is shown once
             driftA (awaiting-review)

  → invariant state validate           callouts close the block after a blank line
```

- The wordmark line is the only heading. There is no rule, banner, or box.
- A success block keeps the wordmark and sets the title in Ok: `Invariant  Change landed`.
- Labels are the record names in sentence case, right-padded to the widest label.
- `Status` values are toned by state; other values are plain.
- `Next`, `Warning`, `Error`, `Invalid`, `Request`, and `Command` records are callouts. They
  are removed from their record position and rendered last, in order, one per line. `Next`,
  `Request`, and `Command` glyphs are Accent; `Warning` is Warn; `Error` and `Invalid` are Bad.
- Non-record lines pass through unchanged and reset label folding.

Failure:

```text
× no coding agent is connected; run 'invariant connect codex'   bad mark, plain message
Invariant  Change
  Change     add-div
  Status     needs attention

  → invariant connect codex
```

The message goes to standard error with its `Invariant:` prefix removed; retained-state
records follow on standard output as an ordinary block.

Conversation:

```text
Invariant  conversation
  codex  ·  ask mode  ·  session 1
  :help for commands  ·  Ctrl-C to leave

(ask) › what owns job recovery?         muted mode, accent ›, plain question (redrawn after Enter)

(codex) › thinking ⠹ · 4s               the agent's line while it works, muted detail
(codex) › 4.2s                          the same line once settled: muted duration only
  The job runner owns recovery. Restart re-queues every non-terminal
  job once …

  ────────────────────────              turn rule: 24 columns, muted, indented, blank line each side

(ask) › next question
```

- Both parties speak from the same shape: `(role) ›`. The user's role is the session mode,
  `ask` or `change`, in Muted; the agent's role is its provider name, `codex` or `claude`, in
  Accent. The `›` is Accent for both.
- The question line is redrawn in that shape once Enter is pressed, when it fits on one physical
  line.
- The agent's line is its activity line: `thinking` plus the spinner while it works, with the
  elapsed time after three seconds, replaced in place by the duration alone when the answer
  arrives, or by `×` and the duration on failure. It stays in the transcript.
- Agent prose follows on the next lines at a measure of 88 columns or the terminal width minus
  four, indented two spaces, with list items hanging under their marker.
- Markdown headings, `**strong**` spans, and `` `code` `` spans render in Strong with their
  markers removed; fenced code blocks are kept verbatim and unwrapped, indented four spaces.
- Each turn ends with the turn rule. One-shot `ask` prints the question line, one blank line,
  and the agent's line and prose, with no rule.
- Invariant headings are reserved for system state.

## Terminal motion

- One transient activity line on standard error: `⠹ Codex is implementing the change`, in Muted.
- After three seconds the line gains a duration: `⠹ Codex is implementing the change · 12s`.
- When the step finishes the line is replaced by one settled trail line and stays:
  `✓ Codex implemented the change · 42s`, or `× Codex is implementing the change · 3.1s` on
  failure. Trail labels are past tense for completion and present tense for failure.
- Conversation turns use the agent's own `(provider) ›` line as their activity line instead.
- Durations render as `4.2s` under ten seconds, `12s` under a minute, then `1m 05s`.
- Animation and trail lines are disabled when either standard output or standard error is not a
  terminal, under `CI`, when `TERM=dumb`, or with `INVARIANT_NO_ANIMATION=1`. No other motion
  exists: no progress bars, no bells, no cursor effects outside the questionnaire.

## Terminal questionnaire

```text
SETUP  2/5                             muted progress
Authority                              strong title
Who may define repository-wide meaning?

  ● Agent  recommended                 accent marker on the active option, amber recommendation
    Resolve meaning within granted limits.
  ○ Human                              muted marker on inactive options
```

Arrow keys or `j`/`k` move, Enter selects, and the cursor is hidden while selecting. Without a
terminal the same options print as lines and a `› Choice [default]:` prompt reads one value.
