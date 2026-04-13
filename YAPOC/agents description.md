
## Base agents.

Base agents is a special type of fixed agents which forms overall system.
Types of agents:
* Master Agent
	* Planning Agent
	* Builder Agent
	* Keeper Agent
	* Cron Agent
	* Doctor agent

Each agent has a special types of .md files:
PROMPT.MD
TASK.MD
MEMORY.MD
NOTES.MD
HEALTH.MD

by default agents will be isolated from each other, except *Plannig agent*
### Master agent

Entry point for system interaction, only via that agent is allowed:
* Change system configuration
* Creating/Deleting/Editing other agents
* Delegating task


To do that it will have separate subagents/tools.
### Planning agent
Creating a detailed execution plan for provided tasks. 
Will be capable of editing other's TASK.MD files. 

Should be called directly from Master Agent and providing task description to target agent (even master itself).

### Builder agent
Capable of creating/deleting/editing other agents (expect base ones).
Will be able to edit project's file system related to agent's folders.

Should be called directly from Planning Agent.

### Keeper Agent
Edit project setting and configurations.

Should be called directly from Planning Agent.

### Cron Agent
Simple delayed task manager.
Will be able to create a timed task that will auto executed at specified period of time.
Should be called directly from Planning Agent.

### Doctor agent
Had a separate cron for it's own work. Can read through others HEALTH.MD to summarise and modify errors that other agents' does

## Files description:

PROMPT.MD - main prompt of a specific agent, contains role, personality, do and don't
TASK.MD - file with current agent task with description descriptive
MEMORY.MD - short, log like file, with key points for each entry for more easy for agent to "remember" things and do repeated jobs
NOTES.MD some specific examples of knowledge, that note categorized as memory - information about user, project, specific behaviour and etc
HEALTH.MD - log for personal errors to avoid them in future