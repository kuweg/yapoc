# YAPOC workspace UI

The interface puts the conversation with Master in the center and makes the
collaborating agent team visible beside it. A connected-node mark identifies
YAPOC without relying on decorative effects or invented activity.

## Information architecture

| Navigation group | Destinations |
| --- | --- |
| Workspace | Conversation, Agents, Tasks, Artifacts, Workspace files |
| Intelligence | Insights, Observability, Concilium, Memory, Vault, Skills |
| Connections | MCP servers, Plugins |
| Communication | Conversations (history), Channels |

New conversation is a persistent action above these groups. Artifacts and
Workspace files open inspectors alongside the conversation; selecting either
from another destination first returns to the conversation. Ctrl+K / Cmd+K
opens the command palette, including these inspectors and all navigation items.

## Component hierarchy and layout

```text
App / studio-shell
  StudioNavigation — brand, new conversation, grouped navigation, collapse
  studio-main
    Header — location, Master activity, commands, notifications, theme, team
    Active destination
      ChatPanel
        StudioWelcome or conversation history
        ChatInput and voice/send controls
      Existing feature panels / MCP and plugin tables
    StudioInspector — shared tabs for artifacts, workspace, agent flow, file preview
  AgentSidebar — Master first, actual team activity, agent controls
  LiveTopologyHUD — expandable system activity rail
  CommandPalette
  StudioDialog — focused integration configuration
```

Desktop navigation is 224px wide and can collapse to a 72px icon rail. The
header is 56px high. The optional team inspector is 280px wide. Main content
uses available space and scrolls independently. Open tools share one tabbed
inspector column, with a resizable width bounded to leave at least 440px for
conversation. Below 800px of actual content width, the inspector fills that
area and provides Back to conversation; chat stays mounted with its draft.

Open **Agent flow →** on multiple team cards to compare their flows side by
side. Each agent opens once and has its own close button, scroll position and
usage bar. The dock expands within its existing chat-width limit. When the
available width cannot fit every 320px flow, scroll the flow area horizontally
or select its named tab. Closing one flow preserves the others; Back to
conversation closes the dock's open inspectors.

Each flow's header shows that agent's input/output tokens, throughput, context
usage and a cost estimate from the [shared pricing registry](model-pricing.md).
Live text/reasoning counts are marked as estimates; provider usage events
replace them. Unknown input/pricing stays unavailable rather than showing a
fabricated zero. Reloading a flow restores its latest available activity usage.

Master's conversation metrics sit beside its name and model in an always-visible
header above the chat. The row wraps on narrow screens and retains the last
response's numbers while idle. Before usage is available, it shows dashes.
This responds to the space remaining after navigation and the team, rather
than just viewport width. On narrow screens navigation and the team become
dismissible drawers; the composer takes a full row and the topology rail
retains compact counts.

## Visual system

React components retain the existing Tailwind utilities; `src/studio/studio.css`
provides shared semantic tokens and layout rules, imported after `index.css`.
Dark surfaces use ink tones and one sea-glass accent (`#89d3be`). Existing light
and warm themes remain available. Status colors convey errors and activity.

Use an 8px spacing rhythm, 6–8px control radii, subtle borders, 14px body text,
12px metadata, and 20–24px page titles. System sans-serif is the default;
monospace is reserved for code and technical values. New shell, welcome, and
integration controls use Lucide icons. Hierarchy is page title, primary content,
then supporting metadata. Existing feature panels keep their domain controls.

## Interaction states

| State | Behavior |
| --- | --- |
| New conversation | Three starter rows place an editable draft in the composer; they do not send it. |
| Navigation selected | Accent foreground/background and `aria-current`; collapsed items retain accessible labels and tooltips. |
| Inspector open | Sidebar action shows pressed state; closing preserves the conversation draft. |
| Integration loading | Labeled status with skeleton rows. |
| Integration empty | Explanation and a direct add/reload action. |
| Integration request failure | Error text and retry control. |
| Focused configuration | Native modal dialog contains focus and supports Escape/cancel. |
| Keyboard focus | Visible accent outline on controls. |
| Narrow viewport | Dismissible navigation/team drawers; no page-wide horizontal overflow. |
| Reduced motion | Decorative transitions are disabled. |

The shell continues to mount existing feature panels so navigation preserves
their state. Runtime restart recovery, provider settings, and agent execution
semantics are outside this visual layer.
