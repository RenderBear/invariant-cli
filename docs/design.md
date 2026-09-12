# Design language

The presentation reference for Invariant's explanatory document, README figures, and command-line
output. Machine behavior belongs in [`SPEC.md`](SPEC.md); this file defines only visual and textual
presentation.

## Principles

- Make the authority/execution split visible before showing lifecycle detail.
- Lead with the decision or outcome, then causal evidence and the next valid operation.
- Use text, rules, spacing, and labels for meaning; colour is reinforcement only.
- Keep protocol identifiers and digests copyable and unabridged in machine output.
- Avoid decorative product chrome around repository state.

## Document palette

| Token | Value | Use |
| --- | --- | --- |
| Ink | `#171717` | Body text, primary rules, strong borders |
| Muted | `#626262` | Supporting text, captions, secondary labels |
| Line | `#b8b8b8` | Table cells, ordinary nodes, separators |
| Soft | `#eeeeec` | Headers and limited semantic emphasis |
| Paper | `#ffffff` | Page and component background |
| Accent | `#4f7d1b` | Accepted intent and governed consequence arrows |

Fills stay light enough to print. State is never carried by fill alone.

## Typography

Body text uses the system sans-serif stack:

```css
-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif
```

Identifiers, metadata, code, table headings, and diagram labels use:

```css
ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace
```

Body copy is `15px` with a `1.58` line height. Document titles are `34px`, section headings `24px`,
subsections `18px`, and metadata `10–12px`.

## Geometry and components

- Content width: `1120px` maximum in one centered column.
- Side margin: `20px` minimum.
- Major sections: whitespace plus one horizontal rule.
- Callouts: white background, one-pixel Ink border, square corners, no shadow.
- Cards: use only for repeated parallel concepts.
- Tables: collapsed borders, Soft header, left-aligned values, horizontal overflow when needed.
- Code: very light gray background, thin Line border, no required syntax colouring.

## Diagram language

Use the smallest diagram that makes a boundary or causal sequence clearer. Semantic HTML is
preferred in `model.html`; README figures are accessible SVG.

| Node kind | Background | Border | Label |
| --- | --- | --- | --- |
| Default | Paper | `1px` Ink or Line | Bold title, optional muted detail |
| Protocol boundary | Soft | `2px` Ink | Explicit owner and consequence |
| Derived or rebuildable | Paper | Dashed Line | Say `derived` or `rebuildable` |

- Ordinary arrows are Muted. Accent arrows carry supplied intent or an authorized consequence.
- Dashed arrows denote a request, retry, or return path—not a completed effect.
- Authority and execution occupy separate labeled lanes.
- `intent.resolve` is drawn as a narrow action-bound bridge, never as general agent authority.
- Captions state the architectural claim in prose.
- SVGs are `1200px` wide and include `<title>` and `<desc>`.

## Command-line output

Human output begins with one uppercase protocol outcome and operation name, followed by indented
JSON carrying the exact typed result:

```text
READY: change.recommend
{
  "change": "checkout-copy",
  "stage": "ready"
}
```

Errors put the human message on standard error and retain stable diagnostics in JSON mode. Human
copy may change; protocol fields, outcomes, and diagnostic codes do not change within version 2.

Machine output is one compact JSON object on standard output:

```json
{"protocol":2,"command":"capability.request","status":"ok","outcome":"denied","result":{},"diagnostics":[]}
```

Do not add spinners, dashboards, questionnaires, conversational roles, or inferred next commands to
the kernel CLI. A host may provide those surfaces, but they remain outside repository truth.

## Responsive and print

- Prose and cards collapse to one column; wide diagrams and tables scroll.
- Reading order matches DOM order.
- Black text, white paper, and borders retain the full meaning in grayscale.
- No gradients, textures, drop shadows, rounded dashboard panels, animation, sticky navigation, or
  hover-dependent meaning.
