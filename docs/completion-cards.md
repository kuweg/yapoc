# Mission and result cards

The conversation mission bar shows the current goal, agents confirmed as running,
elapsed time, and a scoped Stop action. Expanding it shows every unfinished task.
It combines task progress with live agent runtime state so a stale handoff does not
continue to describe a finished agent as working.

The assistant answer remains the single narrative result. Its completion card is
an evidence summary: command checks, observed file changes, generated artifacts,
limitations, usage, and Continue/Inspect actions. It deliberately does not repeat
the answer text.

Registered generated files appear inside the result card. Images have thumbnails;
all artifacts have Preview and Download actions. File access continues through the
existing project-root sandbox and artifact provenance APIs.

HTTP and HTTPS links in completed messages receive lazy preview cards. The backend
accepts only public addresses on ports 80 and 443, checks every DNS answer and each
redirect, pins the connection to the checked address, bounds response size and
duration, and proxies only common raster preview images. Failures return an empty
preview so the original link remains usable. Preview URLs are hashed before the
short-lived metadata cache is keyed.
