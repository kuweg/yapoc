I'll create the file with exact content "DONE" (4 bytes, no trailing newline).Now let me verify the byte-exact content.Verification confirms: file contains exactly 4 bytes `D O N E`, no trailing newline (od output ends at offset 0000004 with nothing after).## Done
Created projects/post_restart_probe.txt with exact content "DONE".

## Changes
- Created: projects/post_restart_probe.txt

## Verification
- file_read shows "DONE" (no trailing newline visible).
- wc -c reports 4 bytes; od -c confirms bytes D-O-N-E with nothing after (ends at offset 0000004). Content exactly matches requirement.