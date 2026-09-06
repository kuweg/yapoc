# Negative Knowledge Base
<!-- Rejected approaches, failed experiments, dead-end designs — "we tried X, it didn't work because Y". -->

## LinkedIn page parsing via fetch_page
- status: failed
- decision: Parsing a LinkedIn profile page (www.linkedin.com/in/...) with the fetch_page tool to extract profile content.
- why: LinkedIn returns HTTP 999 (anti-scraping/anti-bot wall). fetch_page does not run JavaScript or hold a session, so LinkedIn blocks the request at the door and no page body ever arrives. Web search (fallback) did surface the profile content.
- by: master
- date: 2026-09-06
