import sys
sys.path.insert(0, '.')
from agent.cli import build_agent

agent, loader, llm_client = build_agent()
pid_id = 'PID_0'

tests = [
    'How many arrows are on this drawing?',
    'Show flow evidence confidence scores',
    'Which pipe runs have no direction assigned?',
    'Show low confidence arrows',
    'How many isolated pipe segments are there?',
    'Show fully isolated equipment symbols',
    'What is the largest connected component?',
    'Show everything reachable from tank67',
    'Show orphan arrows',
    'What percentage of LPS have resolved flow direction?',
    'Show forward vs reverse flow split',
    'Equipment structurally isolated',
    'Confirmed isolated component ids',
    'LPS completely isolated with no adjacent',
]

for q in tests:
    r = agent.answer(q, pid_id=pid_id)
    intent_d = r.get('intent', {})
    intent = intent_d.get('intent_type', '?')
    source = r.get('strategy', '?')
    rows = len(r.get('records', []))
    query_d = r.get('query', {})
    qid = query_d.get('id', '?')
    qid_short = str(qid)[:60] if qid else '?'
    print(f'Q: {q}')
    print(f'  intent={intent}, source={source}, rows={rows}')
    print(f'  qid={qid_short}')
    print()
