"""Single-use isolated builder. Imports trusted host code, edits only its worktree."""
import asyncio
import json
import sys
from pathlib import Path
from app.config import settings


async def main(control: Path):
    # Capture host configuration before selecting a private workspace.
    request = json.loads((control / 'request.json').read_text())
    workspace = Path(request['workspace']).resolve()
    settings._execution_root = workspace
    settings.git_autocheckpoint_enabled = False
    settings.budget_per_task_usd = request['budget_usd'] / 2
    settings.github_enabled = False
    from app.agents.base import BaseAgent, _calc_turn_cost
    from app.utils.adapters import AgentConfig, get_adapter, TextDelta, ToolStart, ToolDone, UsageStats
    from app.utils.secrets import scrub
    from . import write, now
    from .checks import check

    class Builder(BaseAgent):
        async def _load_config(self, config_raw=None):
            return AgentConfig(**request['config'])
        async def _load_adapter(self, config):
            return get_adapter(config)
        async def _load_tool_names(self, config_raw=None):
            return ['file_read', 'file_list', 'file_write', 'file_edit', 'shell_exec']
        async def _emit_event(self, event_type, payload):
            # No parent chat, shared relay, or task notifications from this run.
            pass

    runtime = control / f"universe_{request['id']}_{request['letter']}"
    runtime.mkdir(exist_ok=True)
    (runtime / 'CONFIG.yaml').write_text(f'''runner:
  max_turns: 30
  task_timeout: {request['minutes'] * 60}
sandbox:
  shell_allowlist:
    - ls
    - cat
    - rg
    - grep
    - head
    - tail
    - wc
    - pwd
    - node
    - npm
    - pnpm
    - npx
    - yarn
    - python
    - python3
    - pytest
  forbidden: []
''')
    (runtime / 'PROMPT.MD').write_text('You are an independent builder in a parallel experiment. Implement the user objective in this worktree only. Do not publish, deploy, contact people, or change external services. Your tools have no integration credentials. Install project dependencies if needed. Run the required check. Finish with a concise description of changes and limitations. The peer attempt is unavailable to you.')
    (runtime / 'TASK.MD').write_text(f"---\nstatus: pending\ntoken_limit: 200000\n---\n## Task\n{request['objective']}\n\nApproach: {request['approach']}\nRequirements: {request['requirements']}\nRequired check: {request['check_command']}\n")
    state = json.loads((control / 'state.json').read_text())
    def save(**changes):
        state.update(changes, updated_at=now()); write(control / 'state.json', state)
    def event(kind, **payload):
        path = control / 'events.jsonl'
        if path.exists() and path.stat().st_size > 2_000_000: return
        record = {'type': kind, 'timestamp': now(), 'agent': state['id'], **payload}
        with path.open('a') as stream: stream.write(scrub(json.dumps(record, separators=(',', ':'))) + '\n')
    save(status='running', pid=__import__('os').getpid())
    event('turn_start', model=request['config']['model'])
    try:
        agent = Builder(runtime)
        text = ''
        async with asyncio.timeout(request['minutes'] * 60):
            async for item in agent.run_stream_with_tools():
                if isinstance(item, TextDelta):
                    text = (text + item.text)[-16000:]
                    event('message_delta', text=item.text[:2000])
                elif isinstance(item, ToolStart): event('tool_call', name=item.name, input=item.input)
                elif isinstance(item, ToolDone): event('tool_result', name=item.name, result=str(item.result)[-2000:], is_error=item.is_error)
                elif isinstance(item, UsageStats):
                    cost = _calc_turn_cost(request['config']['model'], item.input_tokens, item.output_tokens, item.cache_creation_tokens, item.cache_read_tokens)
                    save(cost_usd=state['cost_usd'] + cost, input_tokens=state['input_tokens'] + item.input_tokens, output_tokens=state['output_tokens'] + item.output_tokens)
                    if state['cost_usd'] >= request['budget_usd'] / 2:
                        save(status='budget_reached', summary='Estimated spending limit reached. Partial files retained.')
                        return
            save(status='checking', summary=scrub(text)[-6000:])
            result = await check(workspace, request['check_command'])
            save(status='completed', checks=[result])
            event('turn_done', stop_reason='completed')
    except TimeoutError:
        save(status='timeout', summary='Time limit reached; partial files retained.')
    except Exception:
        save(status='failed', summary='Builder stopped. Review the retained activity and partial files.')
        event('error', text='Run failed; provider or tool execution could not complete.')


if __name__ == '__main__':
    asyncio.run(main(Path(sys.argv[1]).resolve()))
