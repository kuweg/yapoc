# Architecture designer

Whiteboard is YAPOC's shared, structured system-design surface. A canvas is
stored in SQLite and contains typed nodes, directional relationships, layout,
provenance and a revision counter. It preserves intent: design a system
visually, reference `@whiteboard` in chat, and Master reads the same
machine-readable design before planning or implementation.

## Designing a system

Create a named canvas from **Whiteboard → + Canvas** and describe what the
design explains. Add actors, components, services, APIs, databases, queues,
events, interfaces, modules, external systems, decisions, or notes from the
left palette. Each node supports prose plus `key: value` details for fields,
endpoints, technologies, constraints, SLOs, ownership, or other contracts.

Choose a relationship and line style in the canvas toolbar, select the connect
control on the source node, then select its target. Relationships are directed:
`calls`, `depends_on`, `reads`, `writes`, `emits`, `subscribes`, `contains`,
`implements`, `extends`, `flows_to`, `blocks`, and `related` retain distinct
meaning in the data agents receive. The canvas saves after every mutation and
refuses stale card updates rather than replacing newer agent work.

## Chat and agents

Mention `@whiteboard` in chat to tell Master to list the canvases, choose the
relevant design, and read all nodes, details, and relationships. Permitted
agents can use:

- `whiteboard_list` to discover canvases and read a complete design.
- `whiteboard_create_canvas` to start a design.
- `whiteboard_add_card` and `whiteboard_update_card` for individual nodes.
- `whiteboard_connect` for typed relationships.
- `whiteboard_apply_design` to generate or extend a whole graph from keyed
  nodes and edges.
- `whiteboard_export` to publish a design into Notes, workspace files, or the
  artifact gallery.

Agent-generated content records the responsible agent. Strings and structured
detail values pass through YAPOC's secret scrubber before storage.

## Export

The Export dialog creates Markdown with a Mermaid diagram, standalone Mermaid,
or structured JSON. A design can be downloaded, written under
`app/projects/designs/`, registered as a versioned artifact, or created as a
Markdown note. Notes export returns a reference suitable for a later chat.

JSON is the lossless interchange format and includes `schema_version`, canvas
metadata, node positions and details, relationships, authors, and revisions.
Mermaid and Markdown are readable projections for documentation and review.
